# Cloud Operations & CI/CD Automation Framework

> **Note:** this is a portfolio reference implementation built to demonstrate
> cloud operations automation patterns (Python CLIs, Ansible, CI pipelines,
> containers, Kubernetes). It is not production infrastructure and contains
> no company internals — all hosts, registries, and endpoints are placeholders.

A small, honest toolkit for routine cloud-ops work:

- **`ops/`** — Python 3.12 CLIs (no hardcoded secrets, dry-run by default):
  - `patching.py` — check pending OS updates via an apt/yum abstraction; `--apply` to actually upgrade
  - `log_rotation.py` — gzip-compress log files older than N days; optional archive pruning
  - `inventory.py` — collect local instance metadata (hostname, OS, CPU, memory, disk, uptime, cloud vendor) as JSON; no network calls
- **`ansible/`** — `patching.yml` (OS updates) and `hardening.yml` (sshd lockdown + logrotate policy) playbooks, plus a `common` role
- **`scripts/`** — `healthcheck.sh` (disk/load/service/HTTP checks) and `backup.sh` (timestamped tar.gz backups with retention)
- **`ci/Jenkinsfile`** — declarative pipeline: lint → unit tests → SonarQube → Checkov → Ansible syntax check → optional image builds
- **`.gitlab-ci.yml`** — stages: validate → test → sast → iac-scan → build
- **`docker/`** — `Dockerfile.ops-runner` (python + ansible) and `Dockerfile.ci-agent` (CI tooling image)
- **`k8s/`** — sample Deployment + Service for an ops agent, plus a nightly log-rotation CronJob
- **`tests/`** — pytest suite covering the `ops` package (no network, no root required)

## Quickstart

```bash
# 1. create a venv and install test deps
python3 -m venv .venv
.venv/bin/pip install pytest

# 2. run the test suite (must pass)
.venv/bin/python -m pytest tests/ -v

# 3. try the CLIs (all safe / read-only by default)
python3 ops/patching.py --dry-run
python3 ops/log_rotation.py /tmp/demo-logs --days 7 --dry-run
python3 ops/inventory.py --pretty
```

## Lint / validate

```bash
# python syntax
python3 -m py_compile $(find ops tests -name "*.py")

# yaml syntax (every .yml/.yaml in the repo)
python3 -c "import yaml, glob; [yaml.safe_load(open(f)) for f in glob.glob('**/*.y*ml', recursive=True)]"

# bash syntax
bash -n scripts/healthcheck.sh scripts/backup.sh

# shellcheck (if installed)
shellcheck scripts/*.sh
```

## Ansible

```bash
cd ansible
cp inventory.ini.example inventory.ini   # then replace placeholder hosts

# syntax check playbooks
ansible-playbook --syntax-check playbooks/patching.yml
ansible-playbook --syntax-check playbooks/hardening.yml

# dry-run against your inventory (safe: --check changes nothing)
ansible-playbook -i inventory.ini playbooks/patching.yml --check
ansible-playbook -i inventory.ini playbooks/hardening.yml --check

# real run (use --limit to roll out gradually)
ansible-playbook -i inventory.ini playbooks/patching.yml --limit web
```

## Docker

```bash
docker build -f docker/Dockerfile.ops-runner -t ops-runner:latest .
docker build -f docker/Dockerfile.ci-agent -t ci-agent:latest .

# run the inventory collector from the image
docker run --rm ops-runner:latest
```

## Kubernetes

```bash
# validate manifests without a cluster
kubectl apply --dry-run=client -f k8s/

# retag the placeholder image first, then apply
kubectl apply -f k8s/
```

## Layout

```
.
├── ops/                 # python CLIs (patching, log_rotation, inventory)
├── tests/               # pytest suite
├── ansible/             # ansible.cfg, example inventory, playbooks, common role
├── scripts/             # healthcheck.sh, backup.sh
├── ci/Jenkinsfile       # declarative Jenkins pipeline
├── .gitlab-ci.yml       # GitLab CI pipeline
├── docker/              # ops-runner + ci-agent images
├── k8s/                 # deployment, service, cronjob manifests
├── LICENSE
└── README.md
```

## License

MIT — see [LICENSE](LICENSE).
