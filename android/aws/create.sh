#!/bin/zsh
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# One-time creation of Tark's Android build machine (A1): an EC2 Ubuntu
# 24.04 x86-64 instance tagged Name=tark-android-builder, reachable only over
# SSM (a security group with no inbound rules, no SSH key), with an IAM role
# that can use SSM and its own S3 bucket only, a 500 GB gp3 disk, and
# "shutdown stops the instance". bootstrap.sh runs as its user data.
#
# The machine costs money while it runs, so this refuses to run unless the
# user approved the type and price: TARK_ANDROID_APPROVED=1 (and optionally
# TARK_ANDROID_TYPE, default c7i.16xlarge).
set -euo pipefail
if [[ ${TARK_ANDROID_APPROVED:-0} != 1 ]]; then
  echo "refusing: set TARK_ANDROID_APPROVED=1 once the user has approved the instance type and price" >&2
  exit 1
fi
HERE=${0:A:h}
R=${TARK_ANDROID_REGION:-ap-south-1}
T=${TARK_ANDROID_TYPE:-c7i.16xlarge}
A=$(aws sts get-caller-identity --query Account --output text)
B=tark-android-builds-$A
ROLE=tark-android-builder

# The bucket: private, jobs expire after 30 days.
if ! aws s3api head-bucket --bucket $B 2>/dev/null; then
  aws s3api create-bucket --bucket $B --region $R --create-bucket-configuration LocationConstraint=$R >/dev/null
fi
aws s3api put-public-access-block --bucket $B --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-lifecycle-configuration --bucket $B --lifecycle-configuration \
  '{"Rules":[{"ID":"jobs-30-days","Status":"Enabled","Filter":{"Prefix":"jobs/"},"Expiration":{"Days":30}}]}'

# The role: SSM, and this bucket only.
if ! aws iam get-role --role-name $ROLE >/dev/null 2>&1; then
  aws iam create-role --role-name $ROLE --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name $ROLE --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  aws iam put-role-policy --role-name $ROLE --policy-name tark-android-bucket --policy-document \
    "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\",\"s3:ListBucket\"],\"Resource\":[\"arn:aws:s3:::$B\",\"arn:aws:s3:::$B/*\"]}]}"
  aws iam create-instance-profile --instance-profile-name $ROLE >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name $ROLE --role-name $ROLE
  sleep 15  # the instance profile takes a moment to be usable
fi

# A security group with no inbound rules (outbound only).
VPC=$(aws ec2 describe-vpcs --region $R --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --region $R --filters Name=group-name,Values=$ROLE Name=vpc-id,Values=$VPC \
  --query 'SecurityGroups[0].GroupId' --output text)
if [[ $SG == None ]]; then
  SG=$(aws ec2 create-security-group --region $R --group-name $ROLE --vpc-id $VPC \
    --description "Tark Android builder: outbound only, reached over SSM" --query GroupId --output text)
fi

AMI=$(aws ec2 describe-images --region $R --owners 099720109477 \
  --filters 'Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*' Name=state,Values=available \
  --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)

aws ec2 run-instances --region $R --image-id $AMI --instance-type $T \
  --iam-instance-profile Name=$ROLE --security-group-ids $SG \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=500,VolumeType=gp3,Iops=6000,Throughput=500,DeleteOnTermination=true}' \
  --instance-initiated-shutdown-behavior stop \
  --metadata-options HttpTokens=required \
  --user-data file://$HERE/bootstrap.sh \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=tark-android-builder}]" \
  --query 'Instances[0].InstanceId' --output text
