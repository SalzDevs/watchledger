.PHONY: all fetch db report serve clean

all: fetch db report

fetch:
	python3 src/fetch.py

db:
	python3 src/build_db.py

report:
	python3 src/report.py

serve:
	python3 src/server.py

clean:
	rm -rf data/raw data/ledger.sqlite* reports/*.html