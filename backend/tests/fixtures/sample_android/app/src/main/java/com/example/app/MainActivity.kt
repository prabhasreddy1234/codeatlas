package com.example.app

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.activity.viewModels
import com.example.app.data.Item
import com.example.app.ui.DetailActivity
import com.example.app.ui.UserViewModel

class MainActivity : AppCompatActivity() {

    private val viewModel: UserViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        viewModel.refresh()
        val item = Item("a")
        render(item)
        findViewById<android.view.View>(0).setOnClickListener {
            startActivity(Intent(this, DetailActivity::class.java))
        }
        mysteryCall()
    }

    private fun render(item: Item) {
        item.title.length
        Helper.log("rendered")
    }
}
