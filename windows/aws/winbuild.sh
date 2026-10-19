#!/bin/zsh
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Drives Tark's Windows build machine from the Mac (W1). The machine is an
# EC2 Windows instance tagged Name=tark-win-builder, reachable only over
# SSM (no inbound ports); it stops itself after each job and after 30 idle
# minutes (windows/aws/bootstrap.ps1).
#
#   winbuild.sh status
#   winbuild.sh start                     start the instance, wait for SSM
#   winbuild.sh job JOB.ps1 [ARGS...]     run a job; prints the S3 prefix
#   winbuild.sh wait COMMAND_ID           wait for a job, print its tail
#   winbuild.sh fetch PREFIX DIR          download a job's artifacts
#   winbuild.sh stop
set -euo pipefail
R=${TARK_WIN_REGION:-ap-south-1}
A=$(aws sts get-caller-identity --query Account --output text)
B=${TARK_WIN_BUCKET:-tark-win-builds-$A}
I=$(aws ec2 describe-instances --region $R \
  --filters Name=tag:Name,Values=tark-win-builder Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
[[ $I == None ]] && { echo "no tark-win-builder instance" >&2; exit 1; }

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
  aws s3 cp --quiet $job s3://$B/$prefix/$name.ps1
  args="-Bucket $B -Prefix $prefix ${*:-}"
  id=$(aws ssm send-command --region $R --instance-ids $I --document-name AWS-RunPowerShellScript \
    --comment "tark $name" --timeout-seconds 600 \
    --output-s3-bucket-name $B --output-s3-key-prefix $prefix/ssm \
    --parameters "$(python3 -c 'import json,sys; b,p,n,a=sys.argv[1:]; print(json.dumps({"executionTimeout":["172800"],"commands":[f"Read-S3Object -BucketName {b} -Key {p}/{n}.ps1 -File C:\\\\tark-job.ps1 -Region ap-south-1 | Out-Null", f"powershell -NoProfile -ExecutionPolicy Bypass -File C:\\\\tark-job.ps1 {a}"]}))' $B $prefix $name "$args")" \
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
*) sed -n '2,17p' $0; exit 2;;
esac
