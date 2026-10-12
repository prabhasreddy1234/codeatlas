package com.example.app.ui;

import android.os.Bundle;
import androidx.appcompat.app.AppCompatActivity;
import com.example.app.Helper;

public class DetailActivity extends AppCompatActivity implements Runnable {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Helper.log("detail");
        run();
    }

    @Override
    public void run() {
        unknownFramework();
    }
}
