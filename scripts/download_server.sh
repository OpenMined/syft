#!/bin/bash

rsync -avz -e "ssh -i ./keys/syftbox.pem" azureuser@20.168.10.234:/home/azureuser/data/ ./data
