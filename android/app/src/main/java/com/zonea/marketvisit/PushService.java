package com.zonea.marketvisit;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.util.Map;

/**
 * Receives Firebase messages and shows them as Android notifications.
 * The server sends data-only messages (title, body, link, tag) so the app always
 * builds the notification itself and knows which screen to open when tapped.
 */
public class PushService extends FirebaseMessagingService {

    static final String CHANNEL_UPDATES = "updates";
    static final String CHANNEL_CHAT = "chat";
    static final String PREFS = "push";
    static final String KEY_TOKEN = "token";

    @Override
    public void onNewToken(String token) {
        saveToken(this, token);
        MainActivity.notifyTokenChanged();
    }

    static void saveToken(Context ctx, String token) {
        ctx.getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_TOKEN, token).apply();
    }

    static String savedToken(Context ctx) {
        return ctx.getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_TOKEN, null);
    }

    static void ensureChannels(Context ctx) {
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        NotificationChannel updates = new NotificationChannel(CHANNEL_UPDATES, "Sales updates and alerts", NotificationManager.IMPORTANCE_DEFAULT);
        updates.setDescription("Daily target, EOD reminders, stock and competitor alerts");
        NotificationChannel chat = new NotificationChannel(CHANNEL_CHAT, "Chat messages", NotificationManager.IMPORTANCE_HIGH);
        chat.setDescription("Messages from your team");
        nm.createNotificationChannel(updates);
        nm.createNotificationChannel(chat);
    }

    @Override
    public void onMessageReceived(RemoteMessage message) {
        Map<String, String> data = message.getData();
        String title = data.get("title");
        String body = data.get("body");
        if (title == null && message.getNotification() != null) {
            title = message.getNotification().getTitle();
            body = message.getNotification().getBody();
        }
        if (title == null) return;
        String link = data.containsKey("link") ? data.get("link") : "#/home";
        String tag = data.containsKey("tag") ? data.get("tag") : "general";
        boolean isChat = tag != null && tag.startsWith("chat");

        ensureChannels(this);
        Intent open = new Intent(this, MainActivity.class)
                .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra(MainActivity.EXTRA_LINK, link);
        int id = tag == null ? 0 : tag.hashCode();
        PendingIntent pi = PendingIntent.getActivity(this, id, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        Notification n = new Notification.Builder(this, isChat ? CHANNEL_CHAT : CHANNEL_UPDATES)
                .setSmallIcon(R.drawable.ic_stat_notify)
                .setColor(Color.parseColor("#2457E6"))
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new Notification.BigTextStyle().bigText(body))
                .setAutoCancel(true)
                .setContentIntent(pi)
                .build();
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) {
            // Same tag replaces the previous one (e.g. one notification per chat).
            nm.notify(id, n);
        }
    }
}
