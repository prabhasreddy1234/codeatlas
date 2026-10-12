package com.example.app.data

import androidx.room.Dao
import androidx.room.Query

@Dao
interface UserDao {
    @Query("SELECT name FROM users")
    fun all(): List<String>
}
