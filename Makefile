build:
	python script/build.py

release: build
	python script/release.py