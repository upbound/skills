# SPDX-License-Identifier: Apache-2.0
"""Tests for author-composition's probe_project.py.

The probe's tags are advice an agent follows without checking, so a wrong one costs a
detour: `up`'s own test and meta models (`io.upbound.dev.*`) serve v1 and v2 projects
alike and must not read as a v1 provider model, and a Kind missing from the model tree may be
a Crossplane type, which `up dep add <xpkg>` cannot add.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROBE = REPO / "skills" / "author-composition" / "scripts" / "probe_project.py"

XRD = """\
apiVersion: apiextensions.crossplane.io/{version}
kind: CompositeResourceDefinition
metadata:
  name: networks.platform.example.org
spec:
  group: platform.example.org
  names:
    kind: Network
    plural: networks
"""


class ProbeProjectTest(unittest.TestCase):
    def project(self, xrd_version: str) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / "upbound.yaml").write_text("apiVersion: meta.dev.upbound.io/v2alpha1\nkind: Project\n")
        (root / "apis" / "networks").mkdir(parents=True)
        for i, version in enumerate(xrd_version.split(",")):  # "v1,v2": a mixed project
            (root / "apis" / "networks" / f"definition{i}.yaml").write_text(XRD.format(version=version))
        (root / "functions" / "fn").mkdir(parents=True)
        (root / "functions" / "fn" / "pyproject.toml").write_text("")  # SDK layout: `models.`
        models = root / ".up" / "python" / "models"
        for dotted, cls in (
            ("io.upbound.dev.meta.e2etest", "E2ETest"),
            ("io.upbound.dev.meta.compositiontest", "CompositionTest"),
            ("io.upbound.aws.ec2.vpc", "VPC"),
            ("io.upbound.m.aws.ec2.vpc", "VPC"),
        ):
            pkg = models / Path(*dotted.split("."))
            pkg.mkdir(parents=True)
            (pkg / "v1beta1.py" if "aws" in dotted else pkg / "v1alpha1.py").write_text(
                textwrap.dedent(f"""\
                    from pydantic import BaseModel
                    class Spec(BaseModel):
                        x: str
                    class {cls}(BaseModel):
                        spec: Spec
                """))
        return root

    def probe(self, root: Path, *kinds: str) -> str:
        p = subprocess.run([sys.executable, str(PROBE), "--project", str(root), *kinds],
                           capture_output=True, text=True)
        return p.stdout + p.stderr

    def line(self, out: str, module: str) -> str:
        return next(l for l in out.splitlines() if f"from models.{module} import" in l)

    def test_dev_meta_model_is_used_in_v2(self):
        out = self.probe(self.project("v2"), "E2ETest")
        line = self.line(out, "io.upbound.dev.meta.e2etest")
        self.assertIn("USE THIS", line)
        self.assertNotIn("do NOT use", line)

    def test_dev_meta_model_is_used_in_v1(self):
        out = self.probe(self.project("v1"), "E2ETest")
        line = self.line(out, "io.upbound.dev.meta.e2etest")
        self.assertIn("USE THIS", line)
        self.assertNotIn("migrating", line)

    def test_dev_meta_model_is_used_in_a_mixed_project(self):
        out = self.probe(self.project("v1,v2"), "E2ETest")
        line = self.line(out, "io.upbound.dev.meta.e2etest")
        self.assertIn("USE THIS", line)
        self.assertNotIn("XRDs only", line)

    def test_non_namespaced_provider_model_still_flagged_in_v2(self):
        out = self.probe(self.project("v2"), "VPC")
        self.assertIn("USE THIS", self.line(out, "io.upbound.m.aws.ec2.vpc"))
        self.assertIn("do NOT use in v2", self.line(out, "io.upbound.aws.ec2.vpc"))

    def test_dev_meta_composition_test_model_is_used_in_v2(self):
        out = self.probe(self.project("v2"), "CompositionTest")
        line = self.line(out, "io.upbound.dev.meta.compositiontest")
        self.assertIn("USE THIS", line)
        self.assertNotIn("do NOT use", line)

    def test_v1_project_uses_the_non_namespaced_provider_model(self):
        out = self.probe(self.project("v1"), "VPC")
        self.assertIn("USE THIS (this project is Crossplane v1)", self.line(out, "io.upbound.aws.ec2.vpc"))
        self.assertIn("only after migrating", self.line(out, "io.upbound.m.aws.ec2.vpc"))

    def test_dev_meta_model_sorts_first_when_a_provider_kind_shares_its_name(self):
        # rank() and the tag must agree: a non-namespaced provider Kind named like up's own
        # model (tagged "do NOT use in v2") must not sort above the meta model, whose place
        # decides which classes get listed.
        root = self.project("v2")
        pkg = root / ".up" / "python" / "models" / "io" / "upbound" / "example" / "e2etest"
        pkg.mkdir(parents=True)
        (pkg / "v1beta1.py").write_text("from pydantic import BaseModel\nclass E2ETest(BaseModel):\n    x: str\n")
        out = self.probe(root, "E2ETest").splitlines()
        first = next(l for l in out if l.lstrip().startswith("from models."))
        self.assertIn("io.upbound.dev.meta.e2etest", first)

    def test_dev_meta_model_sorts_first_in_a_v1_project_too(self):
        # In v1 both models are wanted, so without the meta-first rule the provider's newer
        # v1beta1 would beat up's v1alpha1 and get "USE THIS (this project is Crossplane v1)".
        root = self.project("v1")
        pkg = root / ".up" / "python" / "models" / "io" / "upbound" / "example" / "e2etest"
        pkg.mkdir(parents=True)
        (pkg / "v1beta1.py").write_text("from pydantic import BaseModel\nclass E2ETest(BaseModel):\n    x: str\n")
        out = self.probe(root, "E2ETest").splitlines()
        first = next(l for l in out if l.lstrip().startswith("from models."))
        self.assertIn("io.upbound.dev.meta.e2etest", first)
        self.assertNotIn("USE THIS (this project is Crossplane v1)", "\n".join(out))

    def test_other_dev_upbound_groups_keep_the_namespaced_preference(self):
        # Only io.upbound.dev.meta.* is up's own; another *.dev.upbound.io group is an
        # ordinary API group and its .m. model stays first in v2, even on an older version.
        root = self.project("v2")
        for path, version in (("io/upbound/dev/m/widgets/widget", "v1beta1"),
                              ("io/upbound/dev/widgets/widget", "v1beta2")):
            pkg = root / ".up" / "python" / "models" / path
            pkg.mkdir(parents=True)
            (pkg / f"{version}.py").write_text("from pydantic import BaseModel\nclass Widget(BaseModel):\n    x: str\n")
        out = self.probe(root, "Widget").splitlines()
        first = next(l for l in out if l.lstrip().startswith("from models."))
        self.assertIn("io.upbound.dev.m.widgets.widget", first)

    def test_ga_version_sorts_before_a_higher_major_beta(self):
        # Kubernetes ranks stability before major (v2, v1, v2beta1, v1beta1).
        root = self.project("v2")
        pkg = root / ".up" / "python" / "models" / "io" / "upbound" / "m" / "aws" / "ec2" / "vpc"
        for version in ("v1", "v2beta1"):
            (pkg / f"{version}.py").write_text("from pydantic import BaseModel\nclass VPC(BaseModel):\n    x: str\n")
        out = self.probe(root, "VPC").splitlines()
        first = next(l for l in out if l.lstrip().startswith("from models."))
        self.assertIn("io.upbound.m.aws.ec2.vpc import v1  <- USE THIS", first)

    def test_missing_kind_names_the_crossplane_api_dependency(self):
        out = self.probe(self.project("v2"), "ManagedResourceActivationPolicy")
        self.assertIn("NOT FOUND", out)
        self.assertIn("up dep add --api crossplane:<tag>", out)
        self.assertIn("mrap.md", out)


if __name__ == "__main__":
    unittest.main()
