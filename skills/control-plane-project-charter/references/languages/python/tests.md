# Python: tests

How composition-test assertions are written and dumped in Python. What a suite must contain, and
why, is in [`charter/evidence.md`](../../charter/evidence.md#coverage-what-the-suite-must-contain);
this file is the Python syntax for it. Templates are in [`test-templates.md`](test-templates.md);
the Python index is [`../python.md`](../python.md).

Field names, import paths and class names come from `probe_project.py --fields <Kind>`
([`../python.md`](../python.md)), not from `ls` or `grep` under `.up/python`.

## The coverage shapes in Python

**A minimal XR, inline** (only the XRD-required fields):

```python
spec=compositiontest.Spec(
    compositionPath="apis/encryptedtables/composition.yaml",
    xrdPath="apis/encryptedtables/definition.yaml",
    xr={
        "apiVersion": "platform.example.com/v1alpha1",
        "kind": "EncryptedTable",
        "metadata": {"name": "minimal", "namespace": "default"},
        "spec": {"region": "us-west-2", "hashKey": {"name": "id", "type": "S"}},
    },
    timeoutSeconds=120,
    assertResources=[...],
)
```

The embedded scaffold's `buildTest()` helper usually takes only `xrPath`. `xr` and `xrPath` are
mutually exclusive, so extend the helper with an `xr` parameter rather than duplicating it, and
pass `xrPath=None` on the inline calls:

```python
def buildTest(name, *, xrPath=None, xr=None, assertResources=None):
    return compositiontest.CompositionTest(
        metadata=k8s.ObjectMeta(name=name),
        spec=compositiontest.Spec(
            compositionPath="apis/<kind>/composition.yaml",
            xrdPath="apis/<kind>/definition.yaml",
            xrPath=xrPath, xr=xr,
            timeoutSeconds=120,
            assertResources=assertResources or [],
        ),
    )

test_minimal = buildTest("minimal", xrPath=None, xr={...})
```

**Observed state**, for code gated on `req.observed.resources` or on readiness. Use plain dicts:
`observedResources` is typed `List[Dict[str, Any]]`, and the generated `Condition` model's
`lastTransitionTime` is a `datetime` you do not want to serialize yourself.

```python
observedResources=[{
    "apiVersion": "kms.aws.m.upbound.io/v1beta1",
    "kind": "Key",
    "metadata": {
        "name": "x-key",
        "namespace": "default",
        "annotations": {
            "crossplane.io/composition-resource-name": "key",   # required: keys req.observed.resources["key"]
            "crossplane.io/external-name": "1111",
        },
    },
    "spec": {"forProvider": {"region": "us-west-1"}},
    "status": {
        "atProvider": {"arn": "arn:aws:kms:...:key/1111"},
        # Omit conditions for the "observed but not ready" case.
        "conditions": [
            {"type": "Ready", "status": "True", "reason": "Available",
             "lastTransitionTime": "2026-01-01T00:00:00Z"},
            {"type": "Synced", "status": "True", "reason": "ReconcileSuccess",
             "lastTransitionTime": "2026-01-01T00:00:00Z"},
        ],
    },
}],
```

**Status on the composite.** In Python the write that loses fields is more than one
`resource.update(rsp.desired.composite, {"status": …})` ([`patterns.md`](patterns.md)).

**Absence through `resourceRefs`** on the composite. Copy the list out of `render.log` (written
only by `--function-logs`: [`charter/evidence.md`](../../charter/evidence.md#reading-the-render));
it is matched exactly in length and order:

```python
"spec": {"crossplane": {"resourceRefs": [
    {"apiVersion": "s3.aws.m.upbound.io/v1beta1", "kind": "BucketPublicAccessBlock",
     "name": "example-73dd10b7cb62"},
    {"apiVersion": "s3.aws.m.upbound.io/v1beta1", "kind": "BucketVersioning",
     "name": "example-6f55c6f6ac57"},
    {"apiVersion": "s3.aws.m.upbound.io/v1beta1", "kind": "Bucket",
     "name": "example-bucket"},   # a name the function set itself
]}},
```

## The two dump modes

Python tests are Pydantic objects serialized into the test object model. Which dumps you control
depends on the layout:

| | SDK layout | Embedded layout |
|---|---|---|
| Each asserted resource | `.model_dump(by_alias=True, exclude_unset=True)`: only fields you set are compared, so the assertion stays partial | same |
| The top-level test object | you dump it: `.model_dump(by_alias=True, exclude_none=True)`, then `print(yaml.dump({"items": [...]}))` | the runner does it (`exclude_defaults=True, by_alias=True`, plus None-stripping); you dump nothing |

`by_alias=True` is load-bearing: the model declares `validate_: Optional[bool] =
Field(None, alias='validate')`, and without it the field serializes as `validate_`, which the
runner ignores. The CLI templates ship `assertResources=[]`, so the asserted-resource mode is a
convention; projects vary (one embedded project uses `exclude_unset=True` without `by_alias`).
`exclude_unset` is what keeps the assertion partial.

## Assertion rules

1. Asserted resources carry `apiVersion` and `kind`, unlike resources a function builds.
2. `metadata.namespace` is optional on an expectation: the render carries the XR's namespace,
   and assertions are partial.
3. Do not set `managementPolicies=["*"]` on an expected resource: `exclude_unset` keeps what you
   set, and the assertion then fails against a render that correctly omits it. No
   `exclude={"spec": {"deletionPolicy"}}` either: the `.m.` Spec has no such field.
4. Never exclude `writeConnectionSecretToRef`: it is an API contract.

## Python-specific mistakes

| Mistake | Fix |
|---|---|
| `exclude_none=True` on asserted resources (compares too much), or `exclude_unset=True` on the top-level test | asserted resources `exclude_unset=True`; top-level test `exclude_none=True` |
| `up test generate` before `.up/python` exists: imports do not resolve | `up project build` first, so `crossplane-models` is wired into `pyproject.toml` |
| A function sets, and a test asserts, `providerConfigRef` equal to the model default `{kind: ClusterProviderConfig, name: default}` | up to function-sdk-python 0.12.0 (`up function generate` pins 0.11.0) `resource.update()` dumps with `exclude_defaults`, so that value is missing from the render and the assertion fails; from 0.13.0 `exclude_unset` keeps it. Do not set or assert the default (charter §5); a non-default `providerConfigRef` the project asks for serializes under every version |

## Function unit tests

`up` has no Python unit-test runner and the scaffold ships no test. What works with the venv
`setup_venv.py` builds (checked against function-sdk-python 0.11.0, the version `up function
generate` pins):

| | |
|---|---|
| Framework | stdlib `unittest`: the venv has no pytest, and installing one adds a dependency the project doesn't pin |
| Layout | `functions/<n>/tests/__init__.py` plus `test_*.py`. Without `__init__.py`, discovery fails with `Start directory is not importable` or prints `NO TESTS RAN` (exit 5). The wheel packages only `function/`, so the tests do not ship |
| Imports | `from function import fn`; models as in the function (`from models.io…`) |
| Run | `.venv/bin/python -m unittest discover -s functions/<n>/tests -t functions/<n>` from the project root. `-t` puts `functions/<n>` first on `sys.path`, so `function` is this function even when several functions share the venv (each scaffold names its package `function`). A system `python3` has neither `models` nor the SDK |

A unit test calls `RunFunction` the way Crossplane does, with observed state only. Nothing applies
the XRD: pass every field the XRD requires, defaulted ones included, or the XR model raises
`ValidationError … Field required`.

```python
# functions/<n>/tests/test_fn.py
import asyncio
import unittest

from crossplane.function import resource
from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from function import fn

XR = {
    "apiVersion": "demo.example.org/v1alpha1",
    "kind": "Bucket",
    "metadata": {"name": "example", "namespace": "default"},
    "spec": {"region": "eu-central-1"},
}


def run(xr, observed=None):
    req = fnv1.RunFunctionRequest()
    resource.update(req.observed.composite, xr)
    for key, obj in (observed or {}).items():  # keyed by composition resource name
        resource.update(req.observed.resources[key], obj)
    return asyncio.run(fn.FunctionRunner().RunFunction(req, None))


def fatal_messages(rsp):
    return [r.message for r in rsp.results if r.severity == fnv1.SEVERITY_FATAL]


class TestRunFunction(unittest.TestCase):
    def test_composes_exactly_the_bucket(self):
        rsp = run(XR)
        self.assertEqual(fatal_messages(rsp), [])
        self.assertEqual(sorted(rsp.desired.resources.keys()), ["bucket"])  # surplus fails too
        bucket = resource.struct_to_dict(rsp.desired.resources["bucket"].resource)
        self.assertEqual(bucket["spec"]["forProvider"], {"region": "eu-central-1"})  # absence too

    def test_status_from_observed(self):
        rsp = run(XR, observed={"bucket": {
            "apiVersion": "s3.aws.m.upbound.io/v1beta1", "kind": "Bucket",
            "status": {"atProvider": {"arn": "arn:aws:s3:::example"}},
        }})
        status = resource.struct_to_dict(rsp.desired.composite.resource)["status"]
        self.assertEqual(status, {"bucketArn": "arn:aws:s3:::example"})
        self.assertEqual(rsp.desired.resources["bucket"].ready, fnv1.READY_UNSPECIFIED)

    def test_missing_region_is_fatal(self):
        rsp = run({**XR, "spec": {}})
        self.assertEqual(fatal_messages(rsp), ["spec.region is required"])
        self.assertEqual(len(rsp.desired.resources), 0)  # nothing composed
```

"Nothing composed" is measurable because `response.to(req)` copies the request's desired state,
which this request does not have. Numbers come back from a `Struct` as floats (`5432.0`), which
`assertEqual` treats as equal to `5432`. Checked: with the Fatal branch disabled,
`test_missing_region_is_fatal` fails. `self.log` lines (`[info] Running function`) in the output are
the scaffold's logger, not failures.
