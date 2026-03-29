SEARCHY_SOURCE_ROOT ?= /tmp

.PHONY: up down logs rebuild ps

up:
	SEARCHY_SOURCE_ROOT="$(SEARCHY_SOURCE_ROOT)" docker compose up --build -d --remove-orphans

down:
	docker compose down --remove-orphans --timeout 2

logs:
	docker compose logs -f

rebuild:
	SEARCHY_SOURCE_ROOT="$(SEARCHY_SOURCE_ROOT)" docker compose up --build -d --force-recreate --remove-orphans

ps:
	docker compose ps
