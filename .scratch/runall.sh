set -e
python recompute2.py
python tagger.py > /dev/null
python fingerprint.py > /dev/null
rm -f previews/*.png
python previewcard.py > /dev/null
python dbbuild.py --no-build --extras
python identity.py --no-scan > /dev/null
python makedemo.py > /dev/null
python report.py --top 20 > /dev/null
echo ALLDONE
