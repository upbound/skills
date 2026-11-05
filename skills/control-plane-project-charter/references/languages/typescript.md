# TypeScript

- [Layout](#layout)
- [Function template (`src/function.ts`)](#function-template-srcfunctionts)
- [`src/main.ts`](#srcmaints)
- [`package.json` and `tsconfig.json`](#packagejson-and-tsconfigjson)
- [Build and test](#build-and-test)

> ### `up` v0.55.0 has no TypeScript support
>
> ```
> $ up function generate f --language typescript
> up: error: --language must be one of "go","go-templating","kcl","python" but got "typescript"
> ```
>
> `up test generate` (which adds `yaml`) and `up project init` reject it too. There is no
> TypeScript function builder and no TypeScript model generator, so a function directory `up`
> has to build (one with a `package.json`) fails `up project build` and every `up test run` with
> `no suitable builder found`.
>
> What works instead, all by hand:
>
> | | |
> |---|---|
> | Scaffold | copy the files below (the layout of [`crossplane/function-template-typescript`](https://github.com/crossplane/function-template-typescript)) |
> | Image | `npm ci && npm run build`, then `docker buildx build` into one OCI tarball per architecture ([Build and test](#build-and-test)) |
> | Packaging | declare the function in `upbound.yaml` as a `Tarball` source, so `up` packages your image instead of looking for a builder |
> | Tests | YAML, the fallback test language ([charter §10](../../SKILL.md#10-language-dispatch)); KCL also works, since tests assert the render whatever produced it |
>
> A missing `up` path is a manual step, not a blocker. Test-first (charter §3), `forProvider`
> only (§5) and reporting (§4) apply unchanged. Report which steps you did by hand, so the gap
> stays visible.

| | |
|---|---|
| Compile | `npm ci && npm run build` in the function directory |
| Type-check only | `npx tsc --noEmit` |
| Fast tier | `npm test`, if the project carries the template's jest setup; otherwise call `RunFunction` from a small `node` script on `dist/` |
| Field names and shapes | `.up/json/models/io-upbound-m-<provider>-<service>-<version>-<Kind>.schema.json`, or the Go and Python models beside it |
| Tests | `up test generate <n> --language yaml` |

## Layout

```text
functions/<n>/
├── src/main.ts        # gRPC server bootstrap: copy it, do not edit
├── src/function.ts    # your RunFunction
├── package.json
├── tsconfig.json
├── Dockerfile         # from function-template-typescript
├── dist/              # npm run build
└── node_modules/      # npm ci
```

The SDK is `@crossplane-org/function-sdk-typescript` (0.7.0 when this was written). Its
`FunctionRunner` catches anything `RunFunction` throws and returns it as a fatal result, so the
function needs no `try`/`catch`.

## Function template (`src/function.ts`)

A Bucket, a BucketVersioning when `spec.versioning` is true, and `status.bucketArn` from the
observed bucket: the same function the Go template in [`go/functions.md`](go/functions.md)
implements, so the test cases in [`go/tests.md`](go/tests.md) and
[`go-templating.md`](go-templating.md) fit it (copy generated names from your own render).
Type-checked with SDK 0.7.0 and TypeScript 5.9 under the `tsconfig.json` below, and run against
a hand-built request for each branch; not yet run under `up test run`.

```typescript
import {
  fatal,
  fromObject,
  getDesiredComposedResources,
  getObservedComposedResources,
  getObservedCompositeResource,
  setDesiredComposedResources,
  setDesiredCompositeStatus,
  to,
  type FunctionHandler,
  type Logger,
  type RunFunctionRequest,
  type RunFunctionResponse,
} from '@crossplane-org/function-sdk-typescript';

// The XR's spec. up generates no TypeScript models, so this is written by hand from the XRD.
interface BucketSpec {
  region?: string;
  versioning?: boolean;
}

// Each kind's own service group, with .m. (namespaced managed resources).
const S3 = 's3.aws.m.upbound.io/v1beta1';

export class Function implements FunctionHandler {
  // eslint-disable-next-line @typescript-eslint/require-await
  async RunFunction(req: RunFunctionRequest, logger?: Logger): Promise<RunFunctionResponse> {
    let rsp = to(req); // carries the desired state earlier pipeline steps produced

    const spec = (getObservedCompositeResource(req)?.resource?.['spec'] ?? {}) as BucketSpec;
    if (!spec.region) {
      fatal(rsp, 'spec.region is required');
      return rsp;
    }

    // The key becomes crossplane.io/composition-resource-name. forProvider only: v2 fills in the rest.
    const desired = getDesiredComposedResources(req);
    desired['bucket'] = fromObject({
      apiVersion: S3,
      kind: 'Bucket',
      spec: { forProvider: { region: spec.region } },
    });
    if (spec.versioning) {
      desired['versioning'] = fromObject({
        apiVersion: S3,
        kind: 'BucketVersioning',
        spec: {
          forProvider: {
            region: spec.region,
            bucketSelector: { matchControllerRef: true },
            versioningConfiguration: { status: 'Enabled' }, // an object in s3.aws.m, a list in the old cluster API
          },
        },
      });
    }
    rsp = setDesiredComposedResources(rsp, desired);

    // XR status from an observed composed resource, keyed by composition resource name.
    const arn: unknown = getObservedComposedResources(req)['bucket']?.resource?.['status']?.atProvider?.arn;
    if (typeof arn === 'string') {
      rsp = setDesiredCompositeStatus({ rsp, status: { bucketArn: arn } });
    }

    logger?.debug({ composed: Object.keys(desired) }, 'composed');
    return rsp;
  }
}
```

What is TypeScript-specific here:

- **`apiVersion` is a plain string, so nothing checks it.** Use the kind's own service group:
  `s3.aws.m.upbound.io` for `Bucket`, `ec2.aws.m.upbound.io` for `VPC` and `Subnet`. The bare
  family group `aws.m.upbound.io` holds only `ProviderConfig`, `ClusterProviderConfig` and
  `ProviderConfigUsage`; a `Bucket` under it renders, passes a test that asserts the same
  string, and fails on a control plane, where no such kind exists.
- **Field shapes are not checked either.** `versioningConfiguration` is a list in the old
  cluster-scoped `s3.aws.upbound.io/v1beta1` and an object in `s3.aws.m.upbound.io/v1beta1`.
  Read each shape from `.up/json/models` before writing it; a test written from the same wrong
  assumption passes.
- **Wrap each composed resource with `fromObject`.** The SDK's `Resource` type also requires
  `connectionDetails` and `ready`, so a bare `{ resource: {…} }` does not type-check under
  `strict`. For core Kubernetes kinds, `kubernetes-models` classes with `fromModel` give typed
  objects.
- **Untyped fields need `['…']` access** under `noUncheckedIndexedAccess`, as above.

## `src/main.ts`

Condensed from `function-template-typescript`'s; compiled and started with SDK 0.7.0. Leave it
alone.

```typescript
#!/usr/bin/env node

import { Command, type OptionValues } from 'commander';
import {
  newGrpcServer,
  startServer,
  FunctionRunner,
  type ServerOptions,
} from '@crossplane-org/function-sdk-typescript';
import { pino } from 'pino';
import { Function } from './function.js';

const defaultAddress = '0.0.0.0:9443';
const defaultTlsServerCertsDir = '/tls/server';

const program = new Command('function')
  .option('--address <address>', 'Address at which to listen for gRPC connections', defaultAddress)
  .option('-d, --debug', 'Emit debug logs.', false)
  .option('--insecure', 'Run without mTLS credentials.', false)
  .option('--tls-server-certs-dir <directory>', 'Serve using mTLS certificates in this directory.', defaultTlsServerCertsDir);

function parseArgs(args: OptionValues): ServerOptions {
  return {
    address: typeof args.address === 'string' ? args.address : defaultAddress,
    debug: Boolean(args.debug),
    insecure: Boolean(args.insecure),
    tlsServerCertsDir: typeof args.tlsServerCertsDir === 'string' ? args.tlsServerCertsDir : defaultTlsServerCertsDir,
  };
}

function main() {
  program.parse(process.argv);
  const opts = parseArgs(program.opts());
  const logger = pino({
    level: opts.debug ? 'debug' : 'info',
    formatters: { level: (label: string) => ({ severity: label.toUpperCase() }) },
  });
  try {
    const server = newGrpcServer(new FunctionRunner(new Function(), logger), logger);
    startServer(server, opts, logger);
    process.on('SIGINT', () => {
      server.tryShutdown((err: Error | undefined) => process.exit(err ? 1 : 0));
    });
  } catch (err) {
    logger.error(err);
    process.exit(1);
  }
}

main();
```

## `package.json` and `tsconfig.json`

Trimmed from `function-template-typescript`, which adds jest, eslint and prettier.

```json
{
  "name": "function",
  "version": "0.1.0",
  "type": "module",
  "main": "dist/main.js",
  "scripts": {
    "build": "tsc",
    "tsc": "tsc",
    "local": "node dist/main.js --insecure --debug"
  },
  "dependencies": {
    "@crossplane-org/function-sdk-typescript": "^0.7.0",
    "@types/node": "^24.10.1",
    "commander": "^12.0.0",
    "pino": "^10.1.0",
    "typescript": "^5.9.3"
  }
}
```

```json
{
  "exclude": ["node_modules", "dist", "**/*.test.ts"],
  "compilerOptions": {
    "rootDir": "./src",
    "outDir": "./dist",
    "module": "nodenext",
    "target": "esnext",
    "types": ["node"],
    "sourceMap": true,
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "noUncheckedSideEffectImports": true,
    "moduleDetection": "force",
    "skipLibCheck": true
  }
}
```

## Build and test

`up` v0.55.0 can package a function it does not build: an entry in `upbound.yaml`
`spec.functions` with `source: Tarball` points at one OCI image tarball per architecture, named
`<pathPrefix>-<arch>.tar` (or `.tar.gz`) relative to the project root. The function's package
repository is `<project-repository>_<name>`, the same as a `Directory` function of that name, so
the composition's `functionRef` does not change.

**This route is read from the v0.55.0 source (`pkg/apis/project/v2alpha1`,
`internal/project/build.go`) and has not been run.** Two things in it are easy to miss:

- **Listing `spec.functions` turns automatic discovery off.** Every other function in the
  project must then be listed too, as `source: Directory`, or it is no longer built.
- The image must report the architecture its file name claims, or the build fails.

```yaml
# upbound.yaml
spec:
  architectures: [amd64, arm64]
  functions:
  - source: Directory
    directory: { name: <other-function> }
  - source: Tarball
    tarball: { name: <n>, pathPrefix: build/<n> }
```

```bash
cd functions/<n>
npm ci && npm run build
for arch in amd64 arm64; do
  docker buildx build --platform "linux/$arch" --target image \
    --output "type=docker,dest=../../build/<n>-$arch.tar" .
done
cd ../..
up project build                     # packages the tarballs instead of building
up test run "tests/test-*"           # composition gate; tests/* also runs the e2e programs (charter §7)
```

The `Dockerfile` is the template's: a `node` build stage running a production-only `npm ci`,
then `npm run tsc` (hence that script, and the compiler in `dependencies`), and a distroless
`nodejs` runtime stage named `image` with `ENTRYPOINT ["/nodejs/bin/node", "dist/main.js"]`.
Rebuild the tarballs after every change to `src/`: `up` packages whatever is on disk, so a
stale tarball tests old code without a warning.

A YAML composition test for the template's versioning branch:

```yaml
apiVersion: meta.dev.upbound.io/v1alpha1
kind: CompositionTest
metadata:
  name: versioning-enabled
spec:
  compositionPath: apis/buckets/composition.yaml
  xrdPath: apis/buckets/definition.yaml
  timeoutSeconds: 120
  validate: false
  xr:
    apiVersion: demo.example.org/v1alpha1
    kind: Bucket
    metadata: { name: example, namespace: default }
    spec: { region: eu-central-1, versioning: true }
  assertResources:
  - apiVersion: s3.aws.m.upbound.io/v1beta1
    kind: BucketVersioning
    spec:
      forProvider:
        versioningConfiguration: { status: Enabled }
```

The rest of the suite is in [`go-templating.md`](go-templating.md) (the versioning-off branch
with a `resourceRefs` guard) and [`go/tests.md`](go/tests.md) (the observed bucket driving
`status.bucketArn`), and
[`yaml.md`](yaml.md) has the YAML object model.

| What you see | Cause |
|---|---|
| `no suitable builder found` | a function directory `up` tries to build has a `package.json`: declare it as a `Tarball` function |
| A test passes, the control plane rejects the resource | an `apiVersion` or field shape nothing type-checks: read the render and the JSON schema |
