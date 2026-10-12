package com.example.app

import androidx.work.CoroutineWorker

class SyncWorker : CoroutineWorker() {
    override suspend fun doWork(): Result = Result.success()
}
