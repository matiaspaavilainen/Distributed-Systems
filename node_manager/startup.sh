#!/bin/bash
# filepath: startup.sh

echo "Waiting for all worker pods to be ready..."
while true; do
  python -c "
import socket
import sys
try:
    print('Connecting to worker-0...')
    s0 = socket.create_connection(('worker-0', 50051), timeout=2)
    s0.close()
    print('Connected to worker-0')
    
    print('Connecting to worker-1...')
    s1 = socket.create_connection(('worker-1', 50051), timeout=2)
    s1.close()
    print('Connected to worker-1')
    
    print('Connecting to worker-2...')
    s2 = socket.create_connection(('worker-2', 50051), timeout=2)
    s2.close()
    print('Connected to worker-2')
    
    print('All connections successful')
    exit(0)
except Exception as e:
    print(f'Connection error: {e}')
    exit(1)
"
  if [ $? -eq 0 ]; then
    break
  fi
  echo "Waiting for all worker lookup services..."
  sleep 5
done

echo "All worker lookup services ready! Starting node-manager..."
sleep 5
# Launch the actual node-manager process
exec python /app/main.py