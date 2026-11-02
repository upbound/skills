# Python: test templates

Composition-test and E2E-test templates in Python, SDK and embedded. What a suite must contain is
in [`tests.md`](tests.md) and [`charter/evidence.md`](../../charter/evidence.md); the Python index
is [`../python.md`](../python.md).

## Composition test, SDK layout (`tests/test-<n>/test/__main__.py`)

```python
import yaml
from models.io.upbound.dev.meta.compositiontest import v1alpha1 as compositiontest
from models.io.k8s.apimachinery.pkg.apis.meta import v1 as k8s
from models.io.upbound.m.azure.resourcegroup import v1beta1 as rgv1beta1
from models.io.upbound.m.azure.network.virtualnetwork import v1beta1 as vnetv1beta1

expected_rg = rgv1beta1.ResourceGroup(
    apiVersion="azure.m.upbound.io/v1beta1",          # tests carry apiVersion and kind
    kind="ResourceGroup",
    metadata=k8s.ObjectMeta(name="rg-example-network"),
    spec=rgv1beta1.Spec(
        forProvider=rgv1beta1.ForProvider(location="West Europe", tags={"Environment": "dev"}),
    ),
)

expected_vnet = vnetv1beta1.VirtualNetwork(
    apiVersion="network.azure.m.upbound.io/v1beta1",  # check the version in .up/python/models
    kind="VirtualNetwork",
    metadata=k8s.ObjectMeta(name="vnet-example-network"),
    spec=vnetv1beta1.Spec(
        forProvider=vnetv1beta1.ForProvider(location="West Europe", addressSpace=["10.0.0.0/16"]),
    ),
)

test_network = compositiontest.CompositionTest(
    metadata=k8s.ObjectMeta(name="test-network"),
    spec=compositiontest.Spec(
        compositionPath="apis/networks/composition.yaml",
        xrPath="examples/network/example-network.yaml",
        xrdPath="apis/networks/definition.yaml",
        timeoutSeconds=120,
        validate=False,
        assertResources=[
            expected_rg.model_dump(by_alias=True, exclude_unset=True),     # partial match
            expected_vnet.model_dump(by_alias=True, exclude_unset=True),
            # assertResources matches the composite too: this is how you assert status.
            # There is no assertComposite/assertStatus field.
            {
                "apiVersion": "network.platform.example.io/v1alpha1",
                "kind": "Network",
                "metadata": {"name": "example-network"},
                "status": {"vnetId": "/subscriptions/.../virtualNetworks/vnet-example-network"},
            },
        ],
    ),
)

# Top-level test: exclude_none=True. The runner expects an "items" list.
print(yaml.dump({"items": [test_network.model_dump(by_alias=True, exclude_none=True)]}))
```

A growing suite gets modules, not directories (author-tests, Phase 2): `test/<concern>.py`,
imported in `__main__.py` as `from test import <concern>`.

## Composition test, embedded layout (`tests/test-<n>/main.py`)

What the `up project init` templates generate: `.model.` imports, a `resources.py` beside it, and
module-level test objects. The runner (`uptest-pyrunner`) walks the module with
`inspect.getmembers`, collects every object that has both `apiVersion` and `kind`, and wraps them
in `items` itself, so print nothing.

```python
# tests/test-storagebucket/main.py
from .model.io.upbound.dev.meta.compositiontest import v1alpha1 as compositiontest
from .model.io.k8s.apimachinery.pkg.apis.meta import v1 as metav1
from . import resources

def buildTest(name, observed, expected) -> compositiontest.CompositionTest:
    return compositiontest.CompositionTest(
        metadata=metav1.ObjectMeta(name=name),
        spec=compositiontest.Spec(
            observedResources=[o.model_dump(exclude_unset=True) for o in observed],
            assertResources=[e.model_dump(exclude_unset=True) for e in expected],
            compositionPath="apis/storagebucket/composition.yaml",
            xrPath="examples/storagebucket/example.yaml",
            xrdPath="apis/storagebucket/definition.yaml",
            timeoutSeconds=120,
            validate=False,
        ),
    )

# One module-level object per test; the names are arbitrary.
test1 = buildTest("bucket-not-yet-created", observed=[], expected=[...])
test2 = buildTest("bucket-created", observed=[resources.observed_bucket], expected=[...])
```

A function that returns early until a dependency is observed needs both: one test with
`observed=[]`, one with the dependency present. Two traps from the collection mechanism:

- **Do not end the module with `items = [test.model_dump(...)]`.** A list of dicts has no
  `apiVersion` attribute, so the runner skips it and `test.yaml` comes out empty.
- **Import the module, not its objects.** `from .resources import observed_bucket` makes that
  Bucket a module-level object with `apiVersion` and `kind`, and the runner emits it as a bogus
  test item. Use `from . import resources`, as the templates do.

## E2E test (`tests/e2etest-<n>/test/__main__.py`)

The fields, and which `credentials` block each target needs, are in author-tests' `e2e.md`
reference. This template is the Python syntax for the static-Secret (local control plane) case.

```python
# Generates the E2ETest. Its output carries the credential Secret: by hand (incl. diffs) run it only
# with UP_AZURE_CREDENTIALS=x, never print or save it with real values.
import os
import sys
import yaml
from models.io.k8s.apimachinery.pkg.apis.meta import v1 as k8s
from models.io.upbound.dev.meta.e2etest import v1alpha1 as e2etest
from models.io.upbound.m.azure.clusterproviderconfig import v1beta1 as pcv1beta1
from models.io.example.platform.network import v1alpha1 as networkv1alpha1

# UP_ prefix: only these cross into the generation container (charter §7). A missing or empty
# value fails here, before a control plane exists. That also fails a plain
# `up test run "tests/*"`, which runs this program too: the composition gate is "tests/test-*".
azure_creds = os.environ.get("UP_AZURE_CREDENTIALS") or sys.exit(
    "UP_AZURE_CREDENTIALS is not set: set it for up test run --e2e; to read this output by hand, set it to x")

azure_secret = {
    "apiVersion": "v1", "kind": "Secret",
    "metadata": {"name": "azure-creds", "namespace": "crossplane-system"},
    "stringData": {"credentials": azure_creds},      # plain text; Kubernetes base64-encodes it
}

# ClusterProviderConfig/default: cluster-scoped (no namespace), the default every composed MR
# falls back to when it sets no providerConfigRef.
provider_config = pcv1beta1.ClusterProviderConfig(
    apiVersion="azure.m.upbound.io/v1beta1",
    kind="ClusterProviderConfig",
    metadata=k8s.ObjectMeta(name="default"),
    spec=pcv1beta1.Spec(
        credentials=pcv1beta1.Credentials(
            source="Secret",
            secretRef=pcv1beta1.SecretRef(
                name="azure-creds", namespace="crossplane-system", key="credentials",
            ),
        ),
    ),
)

# The XR under test: mirror the example under examples/.
network_xr = networkv1alpha1.Network(
    apiVersion="network.platform.example.io/v1alpha1",
    kind="Network",
    metadata=k8s.ObjectMeta(name="example-network", namespace="default"),
    spec=networkv1alpha1.Spec(location="West Europe", cidr="10.0.0.0/16", tags={"Environment": "dev"}),
)
# No providerConfigRef on the XR unless its XRD declares one: the model then has no such field,
# so networkv1alpha1.ProviderConfigRef(...) raises AttributeError and a dict value is dropped.

test_e2e = e2etest.E2ETest(
    metadata=k8s.ObjectMeta(name="e2etest-network"),
    spec=e2etest.Spec(
        crossplane=e2etest.Crossplane(autoUpgrade=e2etest.AutoUpgrade(channel="Stable")),
        defaultConditions=["Ready"],
        extraResources=[                    # applied before the manifests, never asserted
            azure_secret,
            provider_config.model_dump(by_alias=True, exclude_none=True),
        ],
        manifests=[                         # resources under test, at least one
            network_xr.model_dump(by_alias=True, exclude_none=True),
        ],
        skipDelete=False,
        timeoutSeconds=4500,                # size to the real resources
    ),
)

print(yaml.dump({"items": [test_e2e.model_dump(by_alias=True, exclude_none=True)]}))
```
