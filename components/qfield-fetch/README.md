# qfield-fetch

Downloads QField release AppImages, and QField and QFieldCloud sources, into one cache.
[pytest-qfield](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/pytest-qfield) and [qfield-driver](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-driver)
fetch through it, and the command line manages the same cache.

Each entry is fetched once, even by parallel processes such as pytest-xdist workers.
Sources are shallow clones of the one ref asked for (`git clone --depth=1 --branch=<ref>`).

## Install

```bash
pip install qfield-fetch
```

Fetching AppImages needs Linux. Cloning needs `git`.

## Command line

```bash
qfield-fetch appimage 4.2.9          # prints .../appimage/4.2.9/AppRun
qfield-fetch source 4.2.9            # tag v4.2.9, prints the checkout
qfield-fetch source master --update  # a branch, cloned again after it moved
qfield-fetch qfieldcloud latest      # newest QFieldCloud release
qfield-fetch list
qfield-fetch remove source v4.2.9
```

Versions take an optional `v`, and `latest` is the newest release. `qff` is a short
alias of `qfield-fetch`.

## Cache

`~/.cache/qfield-fetch` (or `$XDG_CACHE_HOME/qfield-fetch`) by default. Set `QFIELD_FETCH_CACHE_DIR`,
or pass `--cache-dir`, to use another one.

```text
appimage/4.2.9/AppRun
source/v4.2.9/
qfieldcloud/v26.30/
```

## Python

```python
from qfield_fetch import appimage, qfield_source, qfieldcloud_source

app_run = appimage("4.2.9")
checkout = qfield_source("release-4_3", update=True)
```

## Pytest options

The package registers options that pytest-qfield and pytest-qfield-e2e share:

| Option | Env | Ini |
| --- | --- | --- |
| `--qfield-version` | `QFIELD_VERSION` | `qfield_version` |
| | `QFIELD_FETCH_CACHE_DIR` | `qfield_fetch_cache_dir`, relative to the rootdir |

The option wins over the env, and the env over the ini. The `qfield_fetch_cache_dir` fixture
returns the cache in use.
