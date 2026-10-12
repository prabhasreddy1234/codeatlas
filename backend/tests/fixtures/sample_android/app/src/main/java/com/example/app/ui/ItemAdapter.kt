package com.example.app.ui

import com.example.app.data.Item

class ItemAdapter(private val items: List<Item>) {
    fun first(): Item = items[0]
}
