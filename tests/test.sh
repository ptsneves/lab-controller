#!/bin/bash -xe

this_dir="$(dirname $0)"

rm -f $this_dir/lab-controller-*.log
"$this_dir"/../lab-controller.py -l $this_dir/ -d stderr-test -c "$this_dir"/stderr-log.json -p on
find $this_dir/lab-controller-*.log
rm -f $this_dir/lab-controller-*.log

echo Success