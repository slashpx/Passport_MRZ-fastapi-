# elMRZ — High-Performance Passport MRZ OCR API

A production-ready, containerized FastAPI application for extracting data from passport Machine-Readable Zones (MRZ). This project is deployed on AWS ECS Fargate and secured with a Zuplo API Gateway.

---

## 🗂️ Architecture Overview

This project uses a modern, scalable, and secure architecture:

-   **Backend**: A high-performance **FastAPI** (Python) server that handles image processing and OCR.
-   **Containerization**: The application is containerized with **Docker**, allowing it to run consistently in any environment.
-   **Cloud Deployment**: Deployed on **AWS Elastic Container Service (ECS)** using **Fargate** for serverless container orchestration.
-   **Load Balancing**: An **Application Load Balancer (ALB)** distributes traffic to ensure high availability and responsiveness.
-   **API Gateway**: **Zuplo** sits in front of the entire backend, providing API key authentication, rate limiting, and a clean public endpoint.

```
Client Request
      │
      ▼
┌─────────────┐
│   Zuplo     │ (API Gateway: Auth, Rate Limiting)
└─────────────┘
      │
      ▼
┌─────────────┐
│ AWS ALB     │ (Load Balancer)
└─────────────┘
      │
      ▼
┌──────────────────────────┐
│ AWS ECS Service          │ (Auto-scaling group of tasks)
│ ┌──────────┐ ┌──────────┐│
│ │  Task 1  │ │  Task 2  ││
│ │ (Docker) │ │ (Docker) ││
│ └──────────┘ └──────────┘│
└──────────────────────────┘
```

---

## 🚀 Deployment

The infrastructure is defined in `mrz-fargate-stack.yaml` and deployed via AWS CloudFormation. The application is deployed as a Docker container.

### 1. Build and Push the Docker Image

From the project root, run the following commands, replacing the URI with your own Amazon ECR repository URI.

```bash
# 1. Login to AWS ECR
aws ecr get-login-password --region <your-region> | docker login --username AWS --password-stdin <your-aws-account-id>.dkr.ecr.<your-region>.amazonaws.com

# 2. Build the image
docker build -t <your-ecr-repo-uri>:latest .

# 3. Push the image
docker push <your-ecr-repo-uri>:latest
```

### 2. Update the ECS Service

Force the ECS service to pull the new image and redeploy.

```bash
aws ecs update-service --cluster <your-cluster-name> --service <your-service-name> --force-new-deployment --region <your-region>
```

### 3. Zuplo Setup

1.  Create a project at [https://zuplo.com](https://zuplo.com).
2.  Import the OpenAPI spec from `zuplo/routes.oas.json`.
3.  In the Zuplo project settings, set the `BACKEND_BASE_URL` environment variable to the DNS name of your AWS Application Load Balancer.
4.  Configure API key authentication and rate-limiting policies as needed.

---

## 🧪 Test the API

Use `curl` or any API client to test your live Zuplo endpoint.

```bash
# Replace with your Zuplo URL and a valid API Key
curl -X POST https://<your-zuplo-url>.zuplo.app/api/mrz/process \
  -H "Authorization: Bearer <your-zuplo-api-key>" \
  -F "image=@/path/to/your/passport.jpg"
```

---

## 🚀 Load Testing

The `load_test.js` script is configured to test the API's performance under load using `k6`.

### 📌 Configuration

Update the `ZUPLO_URL` and `API_KEY` variables inside `load_test.js` with your specific endpoint and credentials.

### 🚀 Run the Test

```bash
# Install k6 if you haven't already
# (See https://k6.io/docs/getting-started/installation/)

# Run the test
k6 run load_test.js
```
