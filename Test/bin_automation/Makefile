.PHONY: all clean classify

all: classify

clean:
	rm -rf data/output/*

classify: clean
	python src/ingest.py
	python -m src.classifiers.classify
	python -m src.exporters.export

setup:
	pip install -r requirements.txt 