# Show all commands
help:
	@awk 'BEGIN{FS=":.*##"; printf "\nUsage: make <target>\n\nTargets:\n"} \
	/^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

.DEFAULT_GOAL := fast

.PHONY: help fast full seed seed-run schema schema_seed tests start status logs stop \
        start-docker stop-docker api-rebuild api-logs

fast:          ## DB up -> run app (NO schema/seed/tests, NO installs)
	./run-stack.sh fast

full:          ## DB up -> (reset?) -> schema -> seed -> (tests?) -> run app
	./run-stack.sh full

schema:        ## Apply schema (RESET_PUBLIC respected)
	./run-stack.sh schema

schema_seed:   ## Apply schema then seed (tolerant)
	./run-stack.sh schema_seed

seed:          ## Seed only (tolerant)
	./run-stack.sh seed

seed-run:      ## Seed (tolerant) then run app (NO installs)
	./run-stack.sh seed-run

tests:         ## Run pytest only
	./run-stack.sh tests

start:         ## Fast run in background (daemon)
	./run-stack.sh start

status:        ## Show local uvicorn status (daemon or foreground)
	./run-stack.sh status

logs:          ## Tail local uvicorn log (daemon)
	./run-stack.sh logs

stop:          ## Stop ONLY local uvicorn (daemon or foreground)
	./run-stack.sh stop

start-docker:  ## Start db, redis, minio, api (tolerant/idempotent)
	./run-stack.sh start-docker

stop-docker:   ## Stop all docker services
	docker compose down

api-start:  ## Start docker service api)
	docker compose up -d api
	
api-stop:  ## Start docker service api)
	docker compose stop api
	
api-restart:  ## Start docker service api)
	docker compose restart api	
	
api-rebuild:   ## Rebuild API image, then (re)start API
	docker compose build --no-cache api && docker compose up -d api

api-logs:      ## Tail API logs
	docker compose logs -f api
