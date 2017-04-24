#!/bin/bash -xe
yum install -y python-virtualenv

#without sudo create virtualenv and use pip install install packages
virtualenv py2
source py2/bin/activate
pip install troposphere
pip install attr
pip install awacs
pip install awscli
