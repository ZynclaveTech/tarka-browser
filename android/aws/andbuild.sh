#!/bin/zsh
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Drives Tark's Android build machine from the Mac (A1), like
# windows/aws/winbuild.sh. The machine is an EC2 Ubuntu instance tagged
# Name=tark-android-builder, reachable only over SSM; it stops itself after
# each job and after 30 idle minutes (bootstrap.sh). The source goes to it
# over S3 as a git archive of HEAD (plus the ungoogled-chromium submodule's
# commit), so unreviewed work never has to be pushed anywhere public.
#
#   andbuild.sh status
#   andbuild.sh start                     start the instance, wait for SSM
#   andbuild.sh job JOB.sh [ARGS...]      run a job on HEAD; prints the S3 prefix
#   andbuild.sh wait COMMAND_ID           wait for a job, print its tail
#   andbuild.sh fetch PREFIX DIR          download a job's artifacts
#   andbuild.sh stop
set -euo pipefail
REPO=${0:A:h:h:h}
R=${TARK_ANDROID_REGION:-ap-south-1}
A=$(aws sts get-caller-identity --query Account --output text)
B=tark-android-builds-$A
I=$(aws ec2 describe-instances --region $R \
  --filters Name=tag:Name,Values=tark-android-builder Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
[[ $I == None ]] && { echo "no tark-android-builder instance (android/aws/create.sh)" >&2; exit 1; }

state() { aws ec2 describe-instances --region $R --instance-ids $I --query 'Reservations[0].Instances[0].State.Name' --output text; }

case ${1:-} in
status) echo "$I $(state)";;
start)
  [[ $(state) == stopping ]] && aws ec2 wait instance-stopped --region $R --instance-ids $I
  [[ $(state) == stopped ]] && aws ec2 start-instances --region $R --instance-ids $I >/dev/null
  aws ec2 wait instance-running --region $R --instance-ids $I
  until [[ $(aws ssm describe-instance-information --region $R --filters Key=InstanceIds,Values=$I \
      --query 'InstanceInformationList[0].PingStatus' --output text) == Online ]]; do sleep 10; done
  echo "$I running, SSM online";;
job)
  job=$2; shift 2
  name=${job:t:r}
  prefix=jobs/$name-$(date +%Y%m%d-%H%M%S)
  sub=$(git -C $REPO rev-parse HEAD:ungoogled-chromium)
  git -C $REPO archive --format=tar.gz -o /tmp/tark-src-$$.tar.gz HEAD
  aws s3 cp --quiet /tmp/tark-src-$$.tar.gz s3://$B/$prefix/src.tar.gz && rm -f /tmp/tark-src-$$.tar.gz
  aws s3 cp --quiet $job s3://$B/$prefix/$name.sh
  id=$(aws ssm send-command --region $R --instance-ids $I --document-name AWS-RunShellScript \
    --comment "tark $name" --timeout-seconds 600 \
    --output-s3-bucket-name $B --output-s3-key-prefix $prefix/ssm \
    --parameters "$(python3 -c 'import json,sys; b,p,n,s,a=sys.argv[1:]; print(json.dumps({"executionTimeout":["172800"],"commands":[f"aws s3 cp --quiet s3://{b}/{p}/{n}.sh /tmp/tark-job.sh", f"sudo -u ubuntu -H bash /tmp/tark-job.sh {b} {p} {s} {a}"]}))' $B $prefix $name $sub "${*:-}")" \
    --query Command.CommandId --output text)
  echo "command $id"; echo "prefix $prefix";;
wait)
  until s=$(aws ssm get-command-invocation --region $R --command-id $2 --instance-id $I --query Status --output text 2>/dev/null) \
      && [[ $s != InProgress && $s != Pending && $s != Delayed ]]; do sleep 60; done
  echo "status $s"
  aws ssm get-command-invocation --region $R --command-id $2 --instance-id $I \
    --query '[StandardOutputContent,StandardErrorContent]' --output text | tail -30;;
fetch) mkdir -p $3; aws s3 cp --recursive --quiet s3://$B/$2 $3; ls -la $3;;
stop) aws ec2 stop-instances --region $R --instance-ids $I >/dev/null; echo "stopping $I";;
*) sed -n '2,19p' $0; exit 2;;
esac
