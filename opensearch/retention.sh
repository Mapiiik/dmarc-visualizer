#!/bin/bash
# Deletes reports older than RETENTION_AGGREGATE_DAYS, RETENTION_SMTP_TLS_DAYS and
# RETENTION_FAILURE_DAYS, then again every day. 0 keeps that kind of report for good.
#
# parsedmarc names the indexes by the month a report begins in (or the day, without
# monthly_indexes). An index whose whole period is past the limit goes at once, the rest of
# the oldest month report by report.
set -uo pipefail

OPENSEARCH=${OPENSEARCH_URL:-http://opensearch:9200}

# prefix of the indexes, the date field, days to keep
purge() {
  local prefix=$1 field=$2 days=$3 cutoff index period end answer
  if ! [[ $days =~ ^[0-9]+$ ]]; then
    echo "$prefix: \"$days\" is not a number of days, nothing deleted" >&2
    return
  fi
  (( days > 0 )) || return 0
  cutoff=$(date -u -d "-$days days" +%FT%TZ)

  for index in $(curl -fsS "$OPENSEARCH/_cat/indices/$prefix-*?h=index&expand_wildcards=open"); do
    period=${index#"$prefix"-}
    case $period in
      [0-9][0-9][0-9][0-9]-[0-9][0-9]) end=$(date -u -d "$period-01 +1 month" +%F) ;;
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) end=$(date -u -d "$period +1 day" +%F) ;;
      *) continue ;;
    esac
    # The period ends at midnight of that day, so the whole index is older than the cutoff
    if [[ ! $end > ${cutoff%%T*} ]]; then
      curl -fsS -o /dev/null -X DELETE "$OPENSEARCH/$index" && echo "$index: deleted, older than $days days"
    fi
  done

  answer=$(curl -fsS -X POST "$OPENSEARCH/$prefix-*/_delete_by_query?conflicts=proceed&allow_no_indices=true" \
    -H 'Content-Type: application/json' \
    -d "{\"query\": {\"range\": {\"$field\": {\"lt\": \"$cutoff\"}}}}") || return
  [[ $answer =~ \"deleted\":([0-9]+) ]] && (( BASH_REMATCH[1] > 0 )) &&
    echo "$prefix: ${BASH_REMATCH[1]} reports older than $days days deleted"
}

while :; do
  purge dmarc_aggregate date_begin "${RETENTION_AGGREGATE_DAYS:-365}"
  purge smtp_tls date_begin "${RETENTION_SMTP_TLS_DAYS:-365}"
  purge dmarc_failure arrival_date "${RETENTION_FAILURE_DAYS:-90}"
  # What parsedmarc before 10.0 stored
  purge dmarc_forensic arrival_date "${RETENTION_FAILURE_DAYS:-90}"
  sleep 1d
done
