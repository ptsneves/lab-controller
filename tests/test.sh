#!/bin/bash -xe

this_dir="$(dirname $0)"
"$this_dir"/../lab-controller.py -d stderr-test -c "$this_dir"/stderr-log.json -p on