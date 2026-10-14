.PHONY: ci check test dev setup

## Pipeline completo: testes do back e do front, resumo na tela e,
## se tudo passar, sobe os dois servidores (Ctrl+C encerra)
ci:
	@./scripts/ci.sh

## Só as verificações e o resumo, sem subir servidores
check:
	@./scripts/ci.sh --no-serve

test: check

## Sobe backend e frontend direto, sem rodar os testes
dev:
	@./scripts/dev.sh

## Só prepara o ambiente: .venv, dependências e backend/.env local
setup:
	@./scripts/dev.sh --setup-only
