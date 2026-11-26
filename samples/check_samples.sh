#!/bin/bash
# Run Raksha on the demo input and check the expected behaviour. Usage: bash samples/check_samples.sh
cd "$(dirname "$0")/.."
export RAKSHA_SECRET=practice
OUT=samples/demo_output
rm -rf "$OUT"
.venv/bin/python main.py --input samples/demo_input --output "$OUT" || { echo "FAIL: run"; exit 1; }
pass=0; fail=0
ok()  { echo "  PASS  $1"; pass=$((pass+1)); }
bad() { echo "  FAIL  $1"; fail=$((fail+1)); }
chk() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
D=$(ls $OUT/sanitized/notes/discharge_*.txt)
echo "Checks:"
chk "no patient/relative names, phones or IDs anywhere in output" \
    "! grep -rqE 'Arif|Kusum|Yusuf|Salim|Wangmo|आरिफ|यूसुफ|98390|9123456780|9988776655|6910522119|3972|DEMO/26' $OUT"
chk "doctor names kept"                  "grep -q 'Dr. Ramesh Srivastava' $D && grep -q 'Dr. Kavita Rao' $OUT/sanitized/opd/visits.json"
chk "complaint 'C/O fever' kept"         "grep -q 'C/O fever x 3 days' $D"
chk "eponym 'Parkinson' kept"            "grep -q \"Parkinson's disease\" $D"
chk "doses/vitals kept"                  "grep -q 'Ramipril 5 mg 1-0-1' $D && grep -q 'Dolo 650 BD x 5 days' $D && grep -q 'BP 150/90' $D"
chk "file name with PII renamed"         "[ ! -e $OUT/sanitized/notes/discharge_mohammad_arif.txt ]"
chk "broken files quarantined"           "[ ! -e $OUT/sanitized/misc/truncated.json ] && [ ! -e $OUT/sanitized/misc/scan.jpg ]"
P1=$(grep -o 'PSN-[0-9A-Z]*' $D | head -1)
P2=$(grep -o 'PSN-[0-9A-Z]*' $OUT/sanitized/notes/rx_hindi.txt | head -1)
chk "English and Hindi records -> same pseudonym" "[ -n '$P1' ] && [ '$P1' = '$P2' ]"
R0=$(sed -n 2p $OUT/sanitized/registration/patients.csv | cut -d, -f1)
R1=$(sed -n 3p $OUT/sanitized/registration/patients.csv | cut -d, -f1)
chk "two different 'Mohammad Arif' -> different pseudonyms" "[ '$R0' != '$R1' ]"
chk "length of stay still 9 days" ".venv/bin/python -c \"
import re,datetime as d;t=open('$D').read()
a,b=[d.datetime.strptime(x,'%d/%m/%Y') for x in re.findall(r'Date of (?:Admission|Discharge): (\S+)',t)]
assert (b-a).days==9 and a.strftime('%d/%m/%Y')!='01/03/2026'\""
chk "format contract" "python3 ../Secret-Wards-ToolKit/validate_output.py --input samples/demo_input --output $OUT | grep -q 'CONTRACT OK'"
echo "Result: $pass passed, $fail failed"
[ $fail -eq 0 ]
