// filepath: p:\Passport_MRZ\load-test.js
import http from 'k6/http';
import { check, sleep } from 'k6';

// --- Test Configuration ---
const ZUPLO_URL = 'https://mrz-api-main-c1a0bd1.d2.zuplo.dev';
const API_KEY = 'YOUR_ZUPLO_CONSUMER_API_KEY'; // Your consumer API key

// Load the test image file.
// IMPORTANT: This file must exist in the same directory as the script.
// Create a small (e.g., <100KB) test image named 'passport.jpg'
const imageFile = open('passport.jpg', 'b');

export const options = {
  // This defines the "stages" of our test.
  // It will ramp up the number of virtual users (VUs) over time.
  stages: [
    { duration: '30s', target: 10 }, // Ramp up to 10 users over 30 seconds
    { duration: '1m', target: 10 },  // Stay at 10 users for 1 minute
    { duration: '30s', target: 20 }, // Ramp up to 20 users over 30 seconds
    { duration: '1m', target: 20 },  // Stay at 20 users for 1 minute
    { duration: '30s', target: 0 },   // Ramp down to 0 users
  ],
  thresholds: {
    // Define our success criteria.
    // The test will fail if more than 1% of requests have errors.
    'http_req_failed': ['rate<0.01'],
    // The test will fail if 95% of requests take longer than 2.5 seconds.
    'http_req_duration': ['p(95)<2500'],
  },
};

export default function () {
  const url = `${ZUPLO_URL}/api/mrz/process`;

  const payload = {
    image: http.file(imageFile, 'passport.jpg', 'image/jpeg'),
  };

  const params = {
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
    },
  };

  // Send the POST request
  const res = http.post(url, payload, params);

  // Check if the request was successful
  check(res, {
    'is status 200': (r) => r.status === 200,
  });

  // Wait for 1 second before the next request
  sleep(1);
}