#!/bin/bash

# Check if the correct number of arguments are provided
if [ "$#" -ne 2 ]; then
    echo "Usage: ./run.sh </path/to/input.json> </path/to/output.json>"
    exit 1
fi

# Assign the arguments to variables
input_path=$1
output_path=$2

# Run the Python script with the arguments
python3 simulation.py $input_path $output_path