.PHONY: up down clean logs logs-gitlab logs-sherlock status bootstrap gitlab-root-password \
        webhooks scan-all scan neo4j sherlock-build sherlock-logs demo-break help

help:
	@echo "Sherlock local dev targets"
	@echo ""
	@echo " Infra"
	@echo "  make up                    — start all containers (GitLab, DB, broker, CMDB, Neo4j, Sherlock)"
	@echo "  make down                  — stop containers"
	@echo "  make clean                 — stop + wipe volumes (destructive)"
	@echo "  make logs                  — tail all logs"
	@echo "  make logs-gitlab           — tail GitLab logs"
	@echo "  make logs-sherlock         — tail Sherlock logs"
	@echo ""
	@echo " GitLab"
	@echo "  make gitlab-root-password  — print the auto-generated root password"
	@echo "  make bootstrap             — create banking group + push 10 fixture repos"
	@echo "  make status                — list fixture projects in GitLab"
	@echo ""
	@echo " Sherlock"
	@echo "  make sherlock-build        — rebuild the Sherlock image"
	@echo "  make scan-all              — scan all 10 fixture repos into the graph"
	@echo "  make scan app=<name>       — scan one repo"
	@echo "  make webhooks              — register GitLab webhooks pointing at Sherlock"
	@echo "  make demo-break            — open a demo MR that breaks account-service's API"
	@echo "  make neo4j                 — print Neo4j browser URL + credentials"

up:
	docker compose up -d
	@echo ""
	@echo "Services starting. GitLab's first boot still takes 3-5 min."
	@echo "Watch:  make logs-gitlab   /   make logs-sherlock"

down:
	docker compose down

clean:
	docker compose down -v
	rm -rf gitlab-data postgres-data redpanda-data neo4j-data

logs:
	docker compose logs -f --tail=100

logs-gitlab:
	docker compose logs -f gitlab

logs-sherlock:
	docker compose logs -f sherlock

gitlab-root-password:
	@docker compose exec -T gitlab cat /etc/gitlab/initial_root_password 2>/dev/null | grep '^Password:' || \
		echo "Password not yet generated (or already rotated) — wait for GitLab or reset via UI."

bootstrap:
	./scripts/bootstrap-gitlab.sh

status:
	./scripts/status.sh

sherlock-build:
	docker compose build sherlock
	docker compose up -d sherlock

scan-all:
	@curl -fsS -X POST http://localhost:$${SHERLOCK_PORT:-8001}/scan-all | python3 -m json.tool

scan:
	@test -n "$(app)" || (echo "usage: make scan app=<path>" && exit 1)
	@curl -fsS -X POST http://localhost:$${SHERLOCK_PORT:-8001}/scan/$(app) | python3 -m json.tool

webhooks:
	./scripts/register-webhooks.sh

demo-break:
	./scripts/demo-breaking-change.sh

neo4j:
	@echo "Neo4j Browser:  http://localhost:$${NEO4J_HTTP_PORT:-7474}"
	@echo "Bolt URL:       bolt://localhost:$${NEO4J_BOLT_PORT:-7687}"
	@echo "User:           $${NEO4J_USER:-neo4j}"
	@echo "Password:       $${NEO4J_PASSWORD:-sherlock-dev}"
