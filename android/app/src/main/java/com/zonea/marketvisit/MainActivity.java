package com.zonea.marketvisit;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.os.Build;
import android.webkit.GeolocationPermissions;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.core.content.FileProvider;

import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.lang.ref.WeakReference;

/**
 * Thin Android shell around the Market Visit phone app.
 * All screens and data live on the server, so the team gets updates without a new APK.
 * This class only adds what a plain browser tab can't: GPS and camera permissions,
 * the Android back button, and a retry screen when there is no network.
 */
public class MainActivity extends Activity {

    private static final int REQ_FILE = 1;
    private static final int REQ_LOCATION = 2;
    private static final int REQ_CAMERA = 3;
    private static final int REQ_NOTIFY = 4;
    static final String EXTRA_LINK = "link";
    private static WeakReference<MainActivity> current = new WeakReference<>(null);

    private WebView web;
    private View offlineView;
    private View loadingView;
    private String appHost;

    private ValueCallback<Uri[]> fileCallback;
    private WebChromeClient.FileChooserParams pendingFileParams;
    private Uri cameraUri;

    private GeolocationPermissions.Callback geoCallback;
    private String geoOrigin;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        appHost = Uri.parse(BuildConfig.APP_URL).getHost();
        current = new WeakReference<>(this);
        PushService.ensureChannels(this);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#F4F6FA"));

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setGeolocationEnabled(true);
        s.setAllowFileAccess(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setUserAgentString(s.getUserAgentString() + " MarketVisitApp/" + BuildConfig.VERSION_NAME);
        web.addJavascriptInterface(new Bridge(), "AndroidApp");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (appHost != null && appHost.equalsIgnoreCase(uri.getHost())) {
                    return false; // stay inside the app
                }
                // WhatsApp, phone numbers and other sites open in their own apps.
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (ActivityNotFoundException ignored) {
                }
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    offlineView.setVisibility(View.VISIBLE);
                }
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                loadingView.setVisibility(View.GONE);
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                if (hasLocationPermission()) {
                    callback.invoke(origin, true, false);
                } else {
                    geoOrigin = origin;
                    geoCallback = callback;
                    requestPermissions(new String[]{
                            Manifest.permission.ACCESS_FINE_LOCATION,
                            Manifest.permission.ACCESS_COARSE_LOCATION}, REQ_LOCATION);
                }
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) {
                    fileCallback.onReceiveValue(null);
                }
                fileCallback = callback;
                pendingFileParams = params;
                if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
                } else {
                    launchPicker(true);
                }
                return true;
            }
        });

        offlineView = buildOfflineView();
        offlineView.setVisibility(View.GONE);
        loadingView = buildLoadingView();

        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(loadingView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(offlineView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            web.loadUrl(BuildConfig.APP_URL + linkFrom(getIntent()));
        }

        askNotificationPermission();
        fetchPushToken();
    }

    /** "#/chat/5" style link carried by a tapped notification, or "" if none. */
    private static String linkFrom(Intent intent) {
        String link = intent == null ? null : intent.getStringExtra(EXTRA_LINK);
        return (link != null && link.startsWith("#")) ? link : "";
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        String link = linkFrom(intent);
        if (link.isEmpty()) return;
        String url = web.getUrl();
        if (url != null && url.startsWith(BuildConfig.APP_URL)) {
            web.evaluateJavascript("location.hash = " + JSONObject.quote(link) + ";", null);
        } else {
            web.loadUrl(BuildConfig.APP_URL + link);
        }
    }

    private void askNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIFY);
        }
    }

    /** Ask Firebase for this phone's push address; quietly skipped if Firebase isn't set up in this build. */
    private void fetchPushToken() {
        try {
            com.google.firebase.messaging.FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task -> {
                if (task.isSuccessful() && task.getResult() != null) {
                    PushService.saveToken(this, task.getResult());
                    notifyTokenChanged();
                }
            });
        } catch (Exception ignored) {
        }
    }

    /** Tell the web app a (new) push token is available so it can register it with the server. */
    static void notifyTokenChanged() {
        MainActivity a = current.get();
        if (a == null) return;
        a.runOnUiThread(() -> a.web.evaluateJavascript("window.onPushToken && window.onPushToken();", null));
    }

    /** Small bridge the web app can call: window.AndroidApp.getPushToken(). */
    private class Bridge {
        @JavascriptInterface
        public String getPushToken() {
            return PushService.savedToken(MainActivity.this);
        }
    }

    private boolean hasLocationPermission() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    /** Opens the camera directly (plus a gallery option) for the stock-photo button. */
    private void launchPicker(boolean cameraAllowed) {
        Intent camera = null;
        cameraUri = null;
        if (cameraAllowed) {
            try {
                File dir = new File(getCacheDir(), "camera");
                if (!dir.exists() && !dir.mkdirs()) {
                    throw new IOException("Cannot create camera folder");
                }
                File photo = File.createTempFile("stock_", ".jpg", dir);
                cameraUri = FileProvider.getUriForFile(this, getPackageName() + ".files", photo);
                camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                camera.putExtra(MediaStore.EXTRA_OUTPUT, cameraUri);
                camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            } catch (IOException e) {
                camera = null;
                cameraUri = null;
            }
        }

        Intent gallery = new Intent(Intent.ACTION_GET_CONTENT);
        gallery.addCategory(Intent.CATEGORY_OPENABLE);
        gallery.setType("image/*");

        Intent launch;
        boolean captureOnly = pendingFileParams != null && pendingFileParams.isCaptureEnabled();
        if (camera != null && captureOnly) {
            launch = camera;
        } else {
            launch = Intent.createChooser(gallery, "Add stock photo");
            if (camera != null) {
                launch.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{camera});
            }
        }
        try {
            startActivityForResult(launch, REQ_FILE);
        } catch (ActivityNotFoundException e) {
            finishFileChooser(null);
        }
    }

    private void finishFileChooser(Uri[] result) {
        if (fileCallback != null) {
            fileCallback.onReceiveValue(result);
        }
        fileCallback = null;
        pendingFileParams = null;
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_FILE) {
            return;
        }
        Uri[] result = null;
        if (resultCode == RESULT_OK) {
            if (data != null && data.getClipData() != null) {
                int n = data.getClipData().getItemCount();
                result = new Uri[n];
                for (int i = 0; i < n; i++) {
                    result[i] = data.getClipData().getItemAt(i).getUri();
                }
            } else if (data != null && data.getData() != null) {
                result = new Uri[]{data.getData()};
            } else if (cameraUri != null) {
                result = new Uri[]{cameraUri};
            }
        }
        finishFileChooser(result);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        boolean granted = grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;
        if (requestCode == REQ_LOCATION && geoCallback != null) {
            geoCallback.invoke(geoOrigin, hasLocationPermission(), false);
            geoCallback = null;
            geoOrigin = null;
        } else if (requestCode == REQ_CAMERA && fileCallback != null) {
            launchPicker(granted);
        }
    }

    @Override
    public void onBackPressed() {
        if (offlineView.getVisibility() == View.VISIBLE) {
            super.onBackPressed();
        } else if (web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }

    private View buildOfflineView() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(Color.parseColor("#F4F6FA"));
        int pad = dp(32);
        box.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("No connection");
        title.setTextSize(22);
        title.setTextColor(Color.parseColor("#0E1B33"));
        title.setGravity(Gravity.CENTER);
        title.setTypeface(title.getTypeface(), android.graphics.Typeface.BOLD);

        TextView body = new TextView(this);
        body.setText("Market Visit needs the internet to load live sales. Check your mobile data or Wi-Fi and try again.");
        body.setTextSize(15);
        body.setTextColor(Color.parseColor("#5B6B85"));
        body.setGravity(Gravity.CENTER);
        body.setPadding(0, dp(10), 0, dp(24));

        Button retry = new Button(this);
        retry.setText("Try again");
        retry.setAllCaps(false);
        retry.setTextSize(16);
        retry.setTextColor(Color.WHITE);
        retry.setBackgroundColor(Color.parseColor("#2457E6"));
        retry.setOnClickListener(v -> {
            offlineView.setVisibility(View.GONE);
            loadingView.setVisibility(View.VISIBLE);
            String current = web.getUrl();
            if (current == null || !current.startsWith("http")) {
                web.loadUrl(BuildConfig.APP_URL);
            } else {
                web.reload();
            }
        });

        box.addView(title);
        box.addView(body);
        box.addView(retry, new LinearLayout.LayoutParams(dp(200), dp(52)));
        return box;
    }

    /** Shown while the server wakes up and the first page loads. */
    private View buildLoadingView() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(Color.parseColor("#0E1B33"));

        android.widget.ProgressBar spinner = new android.widget.ProgressBar(this);
        spinner.setIndeterminate(true);

        TextView title = new TextView(this);
        title.setText("Market Visit");
        title.setTextSize(26);
        title.setTextColor(Color.WHITE);
        title.setTypeface(title.getTypeface(), android.graphics.Typeface.BOLD);
        title.setPadding(0, dp(20), 0, dp(6));

        TextView body = new TextView(this);
        body.setText("Connecting to live sales…");
        body.setTextSize(15);
        body.setTextColor(Color.parseColor("#C9D3EA"));

        box.addView(spinner, new LinearLayout.LayoutParams(dp(44), dp(44)));
        box.addView(title);
        box.addView(body);
        return box;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
