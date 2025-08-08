#!/usr/bin/env python3
"""
Simple test script to verify the polling implementation works correctly.
This script tests the progress tracking endpoints.
"""

import requests
import json
import time
import uuid

# Configuration
BASE_URL = "http://localhost:8080"
API_BASE = f"{BASE_URL}/api/v1"

def test_progress_endpoints():
    """Test the progress tracking endpoints"""
    
    # Test data
    session_id = str(uuid.uuid4())
    knowledge_id = "test-knowledge-id"
    
    print(f"Testing progress endpoints with session_id: {session_id}")
    print(f"Knowledge ID: {knowledge_id}")
    print("-" * 50)
    
    # Test 1: Get status of non-existent session (should return 404)
    print("Test 1: Get status of non-existent session")
    try:
        response = requests.get(f"{API_BASE}/progress/{session_id}/status")
        print(f"Status: {response.status_code}")
        if response.status_code == 404:
            print("✓ Correctly returned 404 for non-existent session")
        else:
            print(f"✗ Expected 404, got {response.status_code}")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    print()
    
    # Test 2: Test SSE endpoint (should return deprecated message)
    print("Test 2: Test SSE endpoint (should return deprecated message)")
    try:
        response = requests.get(f"{API_BASE}/progress/{session_id}")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            # Read the first line of the SSE response
            lines = response.text.strip().split('\n')
            if lines:
                data_line = lines[0]
                if data_line.startswith('data: '):
                    data = json.loads(data_line[6:])  # Remove 'data: ' prefix
                    if data.get('status') == 'deprecated':
                        print("✓ Correctly returned deprecated message")
                    else:
                        print(f"✗ Expected deprecated status, got {data}")
                else:
                    print(f"✗ Unexpected SSE format: {data_line}")
        else:
            print(f"✗ Expected 200, got {response.status_code}")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    print()
    
    # Test 3: Clear non-existent session (should return 404)
    print("Test 3: Clear non-existent session")
    try:
        response = requests.delete(f"{API_BASE}/progress/{session_id}")
        print(f"Status: {response.status_code}")
        if response.status_code == 404:
            print("✓ Correctly returned 404 for non-existent session")
        else:
            print(f"✗ Expected 404, got {response.status_code}")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    print()
    print("Testing completed!")
    print("Note: To test with real data, you would need to:")
    print("1. Create a knowledge base")
    print("2. Start a file processing session")
    print("3. Use the returned session_id to test the polling endpoints")

if __name__ == "__main__":
    test_progress_endpoints() 