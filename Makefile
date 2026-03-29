.PHONY: up down logs rebuild ps

up:
	docker compose up --build -d --remove-orphans

down:
	docker compose down --remove-orphans --timeout 2

logs:
	docker compose logs -f

rebuild:
	docker compose up --build -d --force-recreate --remove-orphans

ps:
	docker compose ps
