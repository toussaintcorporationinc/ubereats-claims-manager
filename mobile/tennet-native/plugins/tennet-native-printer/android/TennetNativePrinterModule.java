package com.thetennet.mobile.printer;

import android.Manifest;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothSocket;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.core.content.ContextCompat;

import com.facebook.react.bridge.Arguments;
import com.facebook.react.bridge.Promise;
import com.facebook.react.bridge.ReactApplicationContext;
import com.facebook.react.bridge.ReactContextBaseJavaModule;
import com.facebook.react.bridge.ReactMethod;
import com.facebook.react.bridge.ReadableMap;
import com.facebook.react.bridge.ReadableType;
import com.facebook.react.bridge.WritableArray;
import com.facebook.react.bridge.WritableMap;

import java.io.ByteArrayOutputStream;
import java.io.OutputStream;
import java.nio.charset.Charset;
import java.text.Normalizer;
import java.util.Set;
import java.util.UUID;

public class TennetNativePrinterModule extends ReactContextBaseJavaModule {
  private static final UUID SPP_UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB");
  private static final Charset PRINTER_CHARSET = Charset.forName("CP437");

  public TennetNativePrinterModule(ReactApplicationContext reactContext) {
    super(reactContext);
  }

  @NonNull
  @Override
  public String getName() {
    return "TennetNativePrinter";
  }

  @ReactMethod
  public void getCapabilities(Promise promise) {
    try {
      BluetoothAdapter adapter = BluetoothAdapter.getDefaultAdapter();
      WritableMap result = Arguments.createMap();
      result.putBoolean("nativeModuleAvailable", true);
      result.putBoolean("bluetoothSupported", adapter != null);
      result.putBoolean("bluetoothEnabled", adapter != null && adapter.isEnabled());
      result.putBoolean("sunmiCompatible", isSunmiCompatible());
      promise.resolve(result);
    } catch (Exception exception) {
      promise.reject("native_printer_capability_error", exception.getMessage(), exception);
    }
  }

  @ReactMethod
  public void listBluetoothPrinters(Promise promise) {
    try {
      ensureBluetoothConnectPermission();
      BluetoothAdapter adapter = BluetoothAdapter.getDefaultAdapter();
      if (adapter == null || !adapter.isEnabled()) {
        promise.resolve(Arguments.createArray());
        return;
      }

      WritableArray devices = Arguments.createArray();
      Set<BluetoothDevice> bondedDevices = adapter.getBondedDevices();
      for (BluetoothDevice device : bondedDevices) {
        WritableMap row = Arguments.createMap();
        row.putString("name", safeDeviceName(device));
        row.putString("address", device.getAddress());
        row.putString("type", "bluetooth");
        devices.pushMap(row);
      }
      promise.resolve(devices);
    } catch (SecurityException exception) {
      promise.reject("bluetooth_permission_required", exception.getMessage(), exception);
    } catch (Exception exception) {
      promise.reject("bluetooth_list_failed", exception.getMessage(), exception);
    }
  }

  @ReactMethod
  public void printBluetoothTicket(String address, ReadableMap ticket, Promise promise) {
    new Thread(() -> {
      try {
        ensureBluetoothConnectPermission();
        if (!BluetoothAdapter.checkBluetoothAddress(address)) {
          promise.reject("invalid_printer_address", "Adresse Bluetooth invalide.");
          return;
        }

        BluetoothAdapter adapter = BluetoothAdapter.getDefaultAdapter();
        if (adapter == null || !adapter.isEnabled()) {
          promise.reject("bluetooth_disabled", "Bluetooth indisponible ou eteint.");
          return;
        }

        BluetoothDevice device = adapter.getRemoteDevice(address);
        adapter.cancelDiscovery();

        try (BluetoothSocket socket = device.createRfcommSocketToServiceRecord(SPP_UUID)) {
          socket.connect();
          OutputStream outputStream = socket.getOutputStream();
          outputStream.write(buildEscPosTicket(ticket));
          outputStream.flush();
        }

        WritableMap result = Arguments.createMap();
        result.putBoolean("printed", true);
        result.putString("printer", safeDeviceName(device));
        promise.resolve(result);
      } catch (SecurityException exception) {
        promise.reject("bluetooth_permission_required", exception.getMessage(), exception);
      } catch (Exception exception) {
        promise.reject("native_print_failed", exception.getMessage(), exception);
      }
    }).start();
  }

  private byte[] buildEscPosTicket(ReadableMap ticket) throws Exception {
    String restaurantName = value(ticket, "restaurant_name");
    String orderNumber = value(ticket, "uber_order_number");
    String evidenceLabel = value(ticket, "required_evidence_label");
    String ticketReference = value(ticket, "ticket_reference");
    String uploadUrl = value(ticket, "upload_url");
    String amount = value(ticket, "order_amount");
    String currency = value(ticket, "currency");
    String title = value(ticket, "title");

    ByteArrayOutputStream out = new ByteArrayOutputStream();
    write(out, esc("@"));
    write(out, align(1));
    writeLine(out, "TENNET");
    writeLine(out, "Ticket preuve terrain");
    writeLine(out, "");
    write(out, align(0));
    writeRule(out);
    writePair(out, "Restaurant", restaurantName);
    writePair(out, "Commande Uber", orderNumber);
    writePair(out, "Montant", amount.isEmpty() || amount.equals("null") ? "-" : amount + " " + currency);
    writePair(out, "Preuve", evidenceLabel);
    writePair(out, "Reference", ticketReference);
    writeRule(out);
    writeLine(out, title);
    writeLine(out, "1. Imprimer ce ticket.");
    writeLine(out, "2. Photographier ticket + preuve.");
    writeLine(out, "3. TENNET classe le dossier.");
    writeRule(out);
    write(out, align(1));
    write(out, qrCode(uploadUrl));
    writeLine(out, "");
    writeLine(out, ticketReference);
    writeLine(out, uploadUrl);
    writeLine(out, "");
    writeLine(out, "");
    write(out, cut());
    return out.toByteArray();
  }

  private void ensureBluetoothConnectPermission() {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
      int permission = ContextCompat.checkSelfPermission(getReactApplicationContext(), Manifest.permission.BLUETOOTH_CONNECT);
      if (permission != PackageManager.PERMISSION_GRANTED) {
        throw new SecurityException("Permission BLUETOOTH_CONNECT manquante.");
      }
    }
  }

  private boolean isSunmiCompatible() {
    String manufacturer = Build.MANUFACTURER == null ? "" : Build.MANUFACTURER.toLowerCase();
    String model = Build.MODEL == null ? "" : Build.MODEL.toLowerCase();
    if (manufacturer.contains("sunmi") || model.contains("sunmi")) {
      return true;
    }
    try {
      getReactApplicationContext().getPackageManager().getPackageInfo("woyou.aidlservice.jiuiv5", 0);
      return true;
    } catch (Exception ignored) {
      return false;
    }
  }

  private String safeDeviceName(BluetoothDevice device) {
    try {
      String name = device.getName();
      return name == null || name.trim().isEmpty() ? device.getAddress() : name;
    } catch (SecurityException exception) {
      return device.getAddress();
    }
  }

  private String value(ReadableMap map, String key) {
    if (!map.hasKey(key) || map.isNull(key)) {
      return "";
    }
    ReadableType type = map.getType(key);
    if (type == ReadableType.Number) {
      return stripAccents(String.valueOf(map.getDouble(key))).trim();
    }
    if (type == ReadableType.Boolean) {
      return stripAccents(String.valueOf(map.getBoolean(key))).trim();
    }
    String text = map.getString(key);
    return stripAccents(text == null ? "" : text).trim();
  }

  private String stripAccents(String value) {
    String normalized = Normalizer.normalize(value, Normalizer.Form.NFD);
    return normalized.replaceAll("\\p{M}", "").replaceAll("[^\\x20-\\x7E]", "");
  }

  private void writePair(ByteArrayOutputStream out, String label, String value) {
    writeLine(out, label + ": " + (value == null || value.isEmpty() ? "-" : value));
  }

  private void writeRule(ByteArrayOutputStream out) {
    writeLine(out, "--------------------------------");
  }

  private void writeLine(ByteArrayOutputStream out, String value) {
    write(out, (wrap(value, 32) + "\n").getBytes(PRINTER_CHARSET));
  }

  private String wrap(String value, int width) {
    String safe = value == null ? "" : value;
    if (safe.length() <= width) {
      return safe;
    }
    StringBuilder builder = new StringBuilder();
    int index = 0;
    while (index < safe.length()) {
      int end = Math.min(index + width, safe.length());
      builder.append(safe, index, end);
      if (end < safe.length()) {
        builder.append("\n");
      }
      index = end;
    }
    return builder.toString();
  }

  private byte[] qrCode(String data) throws Exception {
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    byte[] bytes = data.getBytes(PRINTER_CHARSET);
    int length = bytes.length + 3;
    int pL = length % 256;
    int pH = length / 256;
    write(out, new byte[] { 0x1D, 0x28, 0x6B, 0x03, 0x00, 0x31, 0x43, 0x06 });
    write(out, new byte[] { 0x1D, 0x28, 0x6B, 0x03, 0x00, 0x31, 0x45, 0x31 });
    write(out, new byte[] { 0x1D, 0x28, 0x6B, (byte) pL, (byte) pH, 0x31, 0x50, 0x30 });
    write(out, bytes);
    write(out, new byte[] { 0x1D, 0x28, 0x6B, 0x03, 0x00, 0x31, 0x51, 0x30 });
    return out.toByteArray();
  }

  private byte[] esc(String command) {
    if ("@".equals(command)) {
      return new byte[] { 0x1B, 0x40 };
    }
    return new byte[0];
  }

  private byte[] align(int value) {
    return new byte[] { 0x1B, 0x61, (byte) value };
  }

  private byte[] cut() {
    return new byte[] { 0x1D, 0x56, 0x42, 0x00 };
  }

  private void write(ByteArrayOutputStream out, byte[] bytes) {
    out.write(bytes, 0, bytes.length);
  }
}
