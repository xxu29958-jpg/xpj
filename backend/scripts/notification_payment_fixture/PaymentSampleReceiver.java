package ticketbox.journey;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

/** Disposable emulator source: posts through Android, never calls Ticketbox. */
public final class PaymentSampleReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (!Build.PRODUCT.contains("sdk")) throw new IllegalStateException("Cloud emulator only");
        int sample = intent.getIntExtra("sample", -1);
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (sample == 4) {
            manager.cancelAll();
            setResultCode(0);
            return;
        }
        String body;
        switch (sample) {
            case 0: body = "花呗还款成功 ¥100.00"; break;
            case 1: body = "白条还款成功 ¥80.00"; break;
            case 2: body = "支付成功 ¥16.80 收款方：瑞幸咖啡"; break;
            case 3: body = "支付成功 ¥999.00 收款方：关闭采集样本"; break;
            case 5: body = "花呗还款成功 ¥60.00"; break;
            case 6: body = "花呗还款成功 ¥61.00"; break;
            default: throw new IllegalArgumentException("Unknown controlled sample");
        }
        manager.createNotificationChannel(new NotificationChannel(
            "cloud-payment-fixture", "Isolated payment samples", NotificationManager.IMPORTANCE_DEFAULT));
        manager.notify(sample, new Notification.Builder(context, "cloud-payment-fixture")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("隔离验证支付通知")
            .setContentText(body)
            .setAutoCancel(true)
            .build());
        setResultCode(0);
    }
}
