import com.google.zxing.BinaryBitmap;
import com.google.zxing.LuminanceSource;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.Result;
import com.google.zxing.common.HybridBinarizer;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.File;
import java.util.HashMap;

/** 验证工具：用 App 同一份 ZXing 解码电脑端 segno 生成的二维码 PNG，打印内容。 */
public class QrCheck {

    static class BufSrc extends LuminanceSource {
        private final byte[] lum;

        BufSrc(BufferedImage img) {
            super(img.getWidth(), img.getHeight());
            int w = img.getWidth(), h = img.getHeight();
            lum = new byte[w * h];
            for (int y = 0; y < h; y++) {
                for (int x = 0; x < w; x++) {
                    int p = img.getRGB(x, y);
                    int r = (p >> 16) & 0xff, g = (p >> 8) & 0xff, b = p & 0xff;
                    lum[y * w + x] = (byte) ((r * 299 + g * 587 + b * 114) / 1000);
                }
            }
        }

        @Override
        public byte[] getRow(int y, byte[] row) {
            int w = getWidth();
            if (row == null || row.length < w) row = new byte[w];
            System.arraycopy(lum, y * w, row, 0, w);
            return row;
        }

        @Override
        public byte[] getMatrix() {
            return lum;
        }
    }

    public static void main(String[] args) throws Exception {
        BufferedImage img = ImageIO.read(new File(args[0]));
        BinaryBitmap bmp = new BinaryBitmap(new HybridBinarizer(new BufSrc(img)));
        Result r = new MultiFormatReader().decode(bmp, new HashMap<>());
        System.out.println("QR=" + r.getText());
    }
}
