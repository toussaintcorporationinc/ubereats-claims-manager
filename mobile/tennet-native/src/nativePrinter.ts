import { NativeModules, PermissionsAndroid, Platform } from "react-native";

import { EvidencePrintTicket } from "./api";

export type NativePrinterDevice = {
  name: string;
  address: string;
  type: "bluetooth";
  bonded?: boolean;
  printerLike?: boolean;
};

type NativePrinterCapabilities = {
  nativeModuleAvailable: boolean;
  bluetoothSupported: boolean;
  bluetoothEnabled: boolean;
  sunmiCompatible: boolean;
};

type TennetNativePrinterModule = {
  getCapabilities: () => Promise<NativePrinterCapabilities>;
  listBluetoothPrinters: () => Promise<NativePrinterDevice[]>;
  scanBluetoothDevices: (timeoutMs: number) => Promise<NativePrinterDevice[]>;
  pairBluetoothDevice: (address: string) => Promise<{ name: string; address: string; bonded: boolean; pairingStarted: boolean }>;
  openBluetoothSettings: () => Promise<boolean>;
  printBluetoothTicket: (address: string, ticket: EvidencePrintTicket) => Promise<{ printed: boolean; printer: string }>;
};

const nativePrinter = NativeModules.TennetNativePrinter as TennetNativePrinterModule | undefined;

export function hasNativePrinter(): boolean {
  return Platform.OS === "android" && Boolean(nativePrinter);
}

export async function getNativePrinterCapabilities(): Promise<NativePrinterCapabilities> {
  if (!hasNativePrinter() || !nativePrinter) {
    return {
      nativeModuleAvailable: false,
      bluetoothSupported: false,
      bluetoothEnabled: false,
      sunmiCompatible: false,
    };
  }
  return nativePrinter.getCapabilities();
}

export async function listNativePrinters(): Promise<NativePrinterDevice[]> {
  if (!hasNativePrinter() || !nativePrinter) {
    return [];
  }
  await ensureBluetoothPermission();
  return nativePrinter.listBluetoothPrinters();
}

export async function scanNativePrinters(timeoutMs = 9000): Promise<NativePrinterDevice[]> {
  if (!hasNativePrinter() || !nativePrinter) {
    return [];
  }
  await ensureBluetoothPermission();
  return nativePrinter.scanBluetoothDevices(timeoutMs);
}

export async function pairNativePrinter(printer: NativePrinterDevice): Promise<void> {
  if (!hasNativePrinter() || !nativePrinter) {
    throw new Error("Module imprimante natif absent dans ce build Android.");
  }
  await ensureBluetoothPermission();
  const result = await nativePrinter.pairBluetoothDevice(printer.address);
  if (!result.pairingStarted) {
    throw new Error("Android n'a pas pu lancer l'appairage Bluetooth.");
  }
}

export async function openNativeBluetoothSettings(): Promise<void> {
  if (!hasNativePrinter() || !nativePrinter) {
    throw new Error("Module imprimante natif absent dans ce build Android.");
  }
  await nativePrinter.openBluetoothSettings();
}

export async function getRecommendedNativePrinter(): Promise<NativePrinterDevice | null> {
  const printers = await listNativePrinters();
  return selectBestPrinter(printers);
}

export async function printTicketOnNativePrinter(ticket: EvidencePrintTicket, selectedPrinter?: NativePrinterDevice | null): Promise<string> {
  if (!hasNativePrinter() || !nativePrinter) {
    throw new Error("Module imprimante natif absent dans ce build Android.");
  }
  const printer = selectedPrinter ?? await getRecommendedNativePrinter();
  if (!printer) {
    throw new Error("Aucune imprimante ticket Bluetooth appairee. Appaire d'abord l'imprimante dans Android.");
  }
  const result = await nativePrinter.printBluetoothTicket(printer.address, ticket);
  return result.printer || printer.name || printer.address;
}

async function ensureBluetoothPermission(): Promise<void> {
  if (Platform.OS !== "android" || Platform.Version < 31) {
    return;
  }
  const granted = await PermissionsAndroid.requestMultiple([
    PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
    PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
    PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
  ]);
  if (
    granted[PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT] !== PermissionsAndroid.RESULTS.GRANTED ||
    granted[PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN] !== PermissionsAndroid.RESULTS.GRANTED
  ) {
    throw new Error("Permission Bluetooth refusee.");
  }
}

function selectBestPrinter(printers: NativePrinterDevice[]): NativePrinterDevice | null {
  if (!printers.length) {
    return null;
  }
  const ranked = [...printers].sort((left, right) => printerScore(right) - printerScore(left));
  return ranked[0];
}

function printerScore(device: NativePrinterDevice): number {
  const name = device.name.toLowerCase();
  let score = 0;
  if (name.includes("sunmi")) score += 100;
  if (name.includes("cloudprint")) score += 90;
  if (name.includes("cloud print")) score += 90;
  if (name.includes("printer")) score += 40;
  if (name.includes("print")) score += 35;
  if (name.includes("pos")) score += 30;
  if (name.includes("ticket")) score += 30;
  if (name.includes("receipt")) score += 30;
  return score;
}
