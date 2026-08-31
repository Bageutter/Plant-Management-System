# github stuff

## workflows

| file | what it does |
| --- | --- |
| `ruff.yml` | python lint gate — runs on **every PR and push** to `main` |
| `integration-ci.yml` | integration CI — builds, smoke-checks, and tears down the stack |
| `amy.yml` | placeholder for amy |
| `yunus.yml` | placeholder for yunus |
| `guhan.yml` | placeholder for guhan |

## integration CI

two jobs, run in order:

1. **validate + build** — runs `docker compose config` then `docker compose build`. if any image fails to build, the smoke check job never runs
2. **smoke check** — spins up the stack, retries each url up to 10 times with a 3s delay, saves logs, and tears everything down whether it passed or failed

urls checked: (*CI Validation Contract*)
- http://127.0.0.1:5000/ (frontend)
- http://127.0.0.1:5001/login (auth)
- http://127.0.0.1:5002/gardens (vgarden)


logs are always saved as a github artifact (even on failure) and the stack is always torn down with `--volumes --remove-orphans` so nothing leaks between runs

## before merging (*Validation Gates*)

all three gates need to be green before you merge:

- **build gate** — all images built cleanly
- **runtime gate** — all smoke checks passed
- **human gate** — at least one teammate reviewed and there are no unresolved comments
