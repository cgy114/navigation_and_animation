# Battery voltage input

- WHEELTEC D153C `ADC` output -> Tianmengxing `PA25` (`U22` pin 5).
- D153C `GND` -> Tianmengxing `GND`.
- PA25 is ADC0 channel 2, IOMUX PINCM55. It must receive the divided ADC
  output, not the battery's VM positive terminal. Verify the ADC output is
  within 0..3.3 V before connecting.

The status line appends `| bat=12.345V` every 100 ms. `B?` reports the filtered
12-bit raw count, ADC input millivolts and inferred battery millivolts.
ADC sampling runs at 50 Hz with an eight-sample moving average. Conversion
completion is polled with a timeout; it does not block the motor control loop.

The reference is VDDA, nominally 3300 mV. The scaling constants are in
`battery.h`:

```
Vbattery = raw / 4095 * VDDA * divider_numerator / divider_denominator
```

The initial divider factor is **11**, based on the same-series **D153B**
manual's 10 kohm / 1 kohm divider. The supplied product image identifies
**D153C**, for which a separate schematic was not available. Treat x11 as
provisional until checked on this hardware: a 12.0 V battery should produce
about 1.091 V at the module ADC output. Compare `B?` with a voltmeter before
using the reported battery voltage for thresholds or battery protection.

Sources:

- [TI MSPM0G3507 datasheet](https://www.ti.com/lit/ds/symlink/mspm0g3507.pdf)
- [TI single conversion example](https://github.com/TexasInstruments/mspm0-sdk/tree/main/examples/nortos/LP_MSPM0G3507/driverlib/adc12_single_conversion)
- [Same-series D153B module manual, section 2.2](https://www.scribd.com/document/813974530/)
