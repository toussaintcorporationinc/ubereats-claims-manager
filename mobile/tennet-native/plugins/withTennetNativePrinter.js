const { AndroidConfig, withAndroidManifest, withDangerousMod, withMainApplication } = require("@expo/config-plugins");
const fs = require("fs");
const path = require("path");

const PERMISSIONS = [
  "android.permission.BLUETOOTH",
  "android.permission.BLUETOOTH_ADMIN",
  "android.permission.BLUETOOTH_CONNECT",
  "android.permission.BLUETOOTH_SCAN",
  "android.permission.ACCESS_FINE_LOCATION",
];

module.exports = function withTennetNativePrinter(config) {
  config = withAndroidManifest(config, (manifestConfig) => {
    const manifest = manifestConfig.modResults;
    for (const permission of PERMISSIONS) {
      AndroidConfig.Permissions.addPermission(manifest, permission);
    }
    return manifestConfig;
  });

  config = withDangerousMod(config, [
    "android",
    async (dangerousConfig) => {
      const projectRoot = dangerousConfig.modRequest.projectRoot;
      const androidRoot = dangerousConfig.modRequest.platformProjectRoot;
      const sourceRoot = path.join(projectRoot, "plugins", "tennet-native-printer", "android");
      const javaDestination = path.join(androidRoot, "app", "src", "main", "java", "com", "thetennet", "mobile", "printer");

      fs.mkdirSync(javaDestination, { recursive: true });
      for (const filename of ["TennetNativePrinterModule.java", "TennetPrinterPackage.java"]) {
        fs.copyFileSync(path.join(sourceRoot, filename), path.join(javaDestination, filename));
      }

      return dangerousConfig;
    },
  ]);

  config = withMainApplication(config, (mainApplicationConfig) => {
    const contents = mainApplicationConfig.modResults.contents;
    mainApplicationConfig.modResults.contents = injectPrinterPackage(contents);
    return mainApplicationConfig;
  });

  return config;
};

function injectPrinterPackage(contents) {
  if (contents.includes("TennetPrinterPackage")) {
    return contents;
  }

  if (contents.includes("class MainApplication") && contents.includes("PackageList(this).packages")) {
    return contents
      .replace(/(import com\.facebook\.react\.PackageList[^\n]*\n)/, "$1import com.thetennet.mobile.printer.TennetPrinterPackage\n")
      .replace(
        /(val packages = PackageList\(this\)\.packages[^\n]*\n)/,
        "$1          packages.add(TennetPrinterPackage())\n",
      );
  }

  if (contents.includes("class MainApplication") && contents.includes("new PackageList(this).getPackages()")) {
    return contents
      .replace(/(import com\.facebook\.react\.PackageList;\n)/, "$1import com.thetennet.mobile.printer.TennetPrinterPackage;\n")
      .replace(
        /(List<ReactPackage> packages = new PackageList\(this\)\.getPackages\(\);\n)/,
        "$1          packages.add(new TennetPrinterPackage());\n",
      );
  }

  throw new Error("Unable to register TENNET native printer package in MainApplication.");
}
