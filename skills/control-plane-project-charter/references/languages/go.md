# Go

Go tests produce the same `CompositionTest` and `E2ETest` objects as every other language. Which
language new tests use: [charter §10](../../SKILL.md#10-language-dispatch). go-templating tests
(`*.gotmpl`) are a different language: [`go-templating.md`](go-templating.md).

| | |
|---|---|
| Scaffold a function | `up function generate <n> <composition-path> --language go` — then read [`go/functions.md`](go/functions.md): the generated `fn_test.go` tests nothing, and the generated condition targets a claim |
| Scaffold a test | `up test generate <n> --language go` (add `--e2e`) — then read [`go/tests.md`](go/tests.md) |
| Models | `.up/go/models`, written by `up project build`. `.up/` is gitignored, so on a fresh clone run `up project build` |
| Fast tier | `go test ./...` in `functions/<n>/` — calls `RunFunction` directly, about a second, no project build |
| Run a test | `up test run tests/test-<n>` runs `go run .` with the test dir as CWD; the program must print `items: [<CompositionTest>…]` |
| Compile | `go vet ./...` or `go build -o /dev/null ./...` — plain `go build ./...` in a single-package module (every generated function and test) writes the executable into that directory (`tests/<t>/<t>` too), and it ends up committed |
| Before committing | `gofmt -l .` (prints nothing), `go vet ./...`, `go mod tidy` in every function and test module |

## Where everything is

| File | What is in it |
|---|---|
| [`go/functions.md`](go/functions.md) | the scaffold and what to change in it, the function-sdk-go v0.5 calls, a function template, a unit-test template, failure modes |
| [`go/tests.md`](go/tests.md) | how `up` runs a Go test, a composition-test template that tests the function template, failure modes |

## Layout

| | Files | What is in it |
|---|---|---|
| Function | `functions/<n>/*.go` | its own module, `package main`: `main.go` (the gRPC server, leave it), `fn.go` (`RunFunction`), `fn_test.go` |
| Test | `tests/<t>/go.mod` | its own module, `package main`: `main.go` prints the tests as YAML |

Every function and every test directory is a separate Go module, so run `go` commands from inside it.

## Imports and models

**The import path is the API group reversed, then the version**, under `dev.upbound.io/models`:

| What | API group → import |
|---|---|
| Namespaced managed resource (v2) | `ec2.aws.m.upbound.io/v1beta1` → `dev.upbound.io/models/io/upbound/m/aws/ec2/v1beta1`, i.e. `…/io/upbound/m/<provider>/<service>/<version>` |
| Cluster-scoped managed resource (v1 projects only) | `ec2.aws.upbound.io/v1beta1` → `…/io/upbound/aws/ec2/v1beta1` |
| Your own XR | `demo.example.org/v1alpha1` → `…/org/example/demo/v1alpha1` |
| Test objects (`CompositionTest`, `E2ETest`) | `…/io/upbound/dev/meta/v1alpha1` |
| `ObjectMeta` | `…/io/k8s/meta/v1` |

**The non-`.m.` tree sits right beside the `.m.` one**, with the same file names:
`.up/go/models/io/upbound/aws/ec2/v1beta1/vpc.go` next to `.up/go/models/io/upbound/m/aws/ec2/v1beta1/vpc.go`.
A search for a Kind returns both. In a v2 project import the `m/` path; importing the other breaks charter §5
(`.m.` groups only), as in any language.

**Inside a model file**, each Kind is a struct (`Bucket`, `BucketSpec`, `BucketSpecForProvider`), and every
field is a pointer with `omitempty`. Read field names from the file; don't guess them:

```bash
grep -n 'type BucketSpecForProvider struct' -A 60 .up/go/models/io/upbound/m/aws/s3/v1beta1/bucket.go
```

A multi-word Kind's file is its lower-cased name (`routetableassociation.go`). Go field names upper-case
initialisms (`MapPublicIPOnLaunch` for `mapPublicIpOnLaunch`, `EnableDNSHostnames`), so search by the JSON
tag, not a guessed field name: `grep -n 'json:"mapPublicIpOnLaunch' <file>`.

The `apiVersion` and `kind` constants are generated, and their spelling varies **per kind within one tree**:
v0.55.0 writes `VPCApiVersionec2AwsMUpboundIoV1Beta1` next to `InternetGatewayAPIVersionec2AwsMUpboundIoV1Beta1`.
Copy each from the `const (` block at the top of its own file; a grep for one spelling misses the other. They
are **typed** (`VPCApiVersion`, not `string`), so pass `string(c)` where a `string` is expected.

### `go.mod`: the models `replace`

`dev.upbound.io/models` cannot be fetched; it exists only as `.up/go/models`. A module reaches it through a
`replace`, and both scaffolds write one (observed on v0.55.0):

```
require (
	dev.upbound.io/models v0.0.0
	...
)

replace dev.upbound.io/models => ../../.up/go/models
```

- **`go mod tidy` drops the `require` while nothing imports a model**, and keeps the `replace`. That is
  expected: `go mod tidy` after the first model import adds the `require` back (as
  `v0.0.0-00010101000000-000000000000`).
- **Keep the `replace` even while it looks unused.** Without it the first model import fails with
  `unrecognized import path "dev.upbound.io/models"`. A module created by hand, with `mkdir` and a copied
  `go.mod`, often has none: scaffold with the CLI instead.
- The path is relative, so it holds only for a module two levels below the project root (`functions/<n>/`,
  `tests/<t>/`).

## Where Go runs

- **A Go test program runs on your machine**, not in a container: `up test run` runs `go mod
  tidy` and `go run .` locally. It sees your full environment and files, and the `UP_` filter
  does not apply; a variable that does not arrive was not exported in the shell that ran `up`.
  Name its inputs `UP_*` anyway, with a comment that the prefix is a convention here: the test
  then ports to KCL and Python, and one `grep UP_` lists what a run needs
  ([`charter/container.md`](../charter/container.md)). A test that works locally may depend on
  something no CI runner has: name everything it reads.
- **The function itself runs in a container** at render time, like every language, with no
  forwarded environment and no host mounts.
- **`up project build` compiles Go** (`go mod tidy` and `ko`), so a function that does not compile
  fails the build.
