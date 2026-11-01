#!/bin/bash
# delta7 live: PJ6 twice (repeatability), then HP 2 and DCC 4. Test copies only. Export OPENAI_API_KEY (the llama-server key) first; it is read from the environment only.
P=~/cast-pilot; D=$P/xray/d7
run() { # book tag
  echo "$(date "+%-I:%M %p") delta7 $1 $2 start" >> $D/chain.log
  cd $P && nice -n 10 ~/epubkit-venv/bin/python -I xray/delta7.py $1 $D/$1-$2.cast.txt live > $D/logs/$1-$2.run 2>&1 < /dev/null
  echo "$(date "+%-I:%M %p") delta7 $1 $2 exit $?" >> $D/chain.log
}
run pj6 a
run pj6 b
grep -E "^(PART|GUARD|PAIR)" $D/pj6-a.cast.txt.log > $D/pj6-a.answers
grep -E "^(PART|GUARD|PAIR)" $D/pj6-b.cast.txt.log > $D/pj6-b.answers
n=$(diff $D/pj6-a.answers $D/pj6-b.answers | grep -c "^<")
echo "$(date "+%-I:%M %p") pj6 a/b differing answer lines: $n; cast diff lines: $(diff $D/pj6-a.cast.txt $D/pj6-b.cast.txt | grep -c '^<')" >> $D/chain.log
if [ "$n" != "0" ]; then echo "$(date "+%-I:%M %p") stopped: runs differ" >> $D/chain.log; exit 1; fi
run hp2 live
run dcc4 live
echo "$(date "+%-I:%M %p") chain done" >> $D/chain.log
