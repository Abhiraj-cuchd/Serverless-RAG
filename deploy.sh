#!/bin/bash

echo "🚀 Starting deployment..."
echo ""

# Step 1 — Sync services into both lambdas
echo "📦 Syncing services..."
rm -rf ingestion_lambda/services/ query_lambda/services/
cp -r services/ ingestion_lambda/services/
cp -r services/ query_lambda/services/
echo "✅ Services synced"
echo ""

# Step 2 — Build
echo "🔨 Building..."
sam build

if [ $? -ne 0 ]; then
  echo "❌ Build failed. Stopping."
  exit 1
fi
echo "✅ Build successful"
echo ""

# Step 3 — Deploy
echo "☁️  Deploying to AWS..."
sam deploy

if [ $? -ne 0 ]; then
  echo "❌ Deploy failed."
  exit 1
fi

echo ""
echo "✅ Deployment complete!"
