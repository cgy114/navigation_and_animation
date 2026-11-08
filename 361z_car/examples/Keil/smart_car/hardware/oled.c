#include "oled.h"
#include "ti_msp_dl_config.h"

#define OLED_SCK_PIN       GPIO_OLED_PIN_SCK_PIN
#define OLED_SDA_PIN       GPIO_OLED_PIN_SDA_PIN
#define OLED_SCK_IOMUX     GPIO_OLED_PIN_SCK_IOMUX
#define OLED_SDA_IOMUX     GPIO_OLED_PIN_SDA_IOMUX
#define OLED_I2C_DELAY     800U  /* About 10 us at the configured 80 MHz CPU clock. */

static uint8_t oled_address;

static void i2c_delay(void)
{
    delay_cycles(OLED_I2C_DELAY);
}

/* Release high instead of driving high, as required by the I2C bus. */
static void sck_high(void) { DL_GPIO_disableOutput(GPIOB, OLED_SCK_PIN); }
static void sck_low(void)  { DL_GPIO_enableOutput(GPIOB, OLED_SCK_PIN); }
static void sda_high(void) { DL_GPIO_disableOutput(GPIOB, OLED_SDA_PIN); }
static void sda_low(void)  { DL_GPIO_enableOutput(GPIOB, OLED_SDA_PIN); }

static void i2c_start(void)
{
    sda_high();
    sck_high();
    i2c_delay();
    sda_low();
    i2c_delay();
    sck_low();
}

static void i2c_stop(void)
{
    sda_low();
    i2c_delay();
    sck_high();
    i2c_delay();
    sda_high();
    i2c_delay();
}

static int i2c_write(uint8_t value)
{
    int bit;
    int ack;

    for (bit = 0; bit < 8; bit++)
    {
        if (value & 0x80U) sda_high();
        else               sda_low();
        i2c_delay();
        sck_high();
        i2c_delay();
        sck_low();
        value <<= 1;
    }

    sda_high();
    i2c_delay();
    sck_high();
    i2c_delay();
    ack = (DL_GPIO_readPins(GPIOB, OLED_SDA_PIN) == 0U);
    sck_low();
    return ack;
}

static int oled_begin(uint8_t control)
{
    i2c_start();
    if (!i2c_write((uint8_t)(oled_address << 1)) || !i2c_write(control))
    {
        i2c_stop();
        return 0;
    }
    return 1;
}

static int oled_command(uint8_t command)
{
    int ok = oled_begin(0x00U);
    if (!ok) return 0;
    ok = i2c_write(command);
    i2c_stop();
    return ok;
}

static int oled_set_position(uint8_t page, uint8_t column)
{
    return oled_command((uint8_t)(0xB0U | page)) &&
           oled_command((uint8_t)(0x00U | (column & 0x0FU))) &&
           oled_command((uint8_t)(0x10U | (column >> 4)));
}

static int oled_clear(void)
{
    uint8_t page;
    uint8_t column;

    for (page = 0; page < 8; page++)
    {
        if (!oled_set_position(page, 0) || !oled_begin(0x40U)) return 0;
        for (column = 0; column < 128; column++)
        {
            if (!i2c_write(0x00U))
            {
                i2c_stop();
                return 0;
            }
        }
        i2c_stop();
    }
    return 1;
}

void oled_show_hello(void)
{
    static const uint8_t init_commands[] = {
        0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40,
        0x8D, 0x14, 0x20, 0x02, 0xA1, 0xC8, 0xDA, 0x12,
        0x81, 0x7F, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0x2E
    };
    /* Five-column, 5x7 lowercase glyphs: h e l l o. */
    static const uint8_t hello[] = {
        0x7F, 0x08, 0x04, 0x04, 0x78, 0x00,
        0x38, 0x54, 0x54, 0x54, 0x18, 0x00,
        0x00, 0x41, 0x7F, 0x40, 0x00, 0x00,
        0x00, 0x41, 0x7F, 0x40, 0x00, 0x00,
        0x38, 0x44, 0x44, 0x44, 0x38, 0x00
    };
    uint32_t i;

    DL_GPIO_initDigitalInputFeatures(OLED_SCK_IOMUX,
                                     DL_GPIO_INVERSION_DISABLE,
                                     DL_GPIO_RESISTOR_PULL_UP,
                                     DL_GPIO_HYSTERESIS_DISABLE,
                                     DL_GPIO_WAKEUP_DISABLE);
    DL_GPIO_initDigitalInputFeatures(OLED_SDA_IOMUX,
                                     DL_GPIO_INVERSION_DISABLE,
                                     DL_GPIO_RESISTOR_PULL_UP,
                                     DL_GPIO_HYSTERESIS_DISABLE,
                                     DL_GPIO_WAKEUP_DISABLE);
    DL_GPIO_clearPins(GPIOB, OLED_SCK_PIN | OLED_SDA_PIN);
    sck_high();
    sda_high();
    i2c_delay();

    /* Most modules use 0x3C; also accept the alternate 0x3D address. */
    oled_address = 0x3CU;
    i2c_start();
    if (!i2c_write((uint8_t)(oled_address << 1)))
    {
        i2c_stop();
        oled_address = 0x3DU;
        i2c_start();
        if (!i2c_write((uint8_t)(oled_address << 1)))
        {
            i2c_stop();
            return;
        }
    }
    i2c_stop();

    for (i = 0; i < sizeof(init_commands); i++)
        if (!oled_command(init_commands[i])) return;

    if (!oled_clear() || !oled_set_position(3, 49) || !oled_begin(0x40U)) return;
    for (i = 0; i < sizeof(hello); i++)
    {
        if (!i2c_write(hello[i]))
        {
            i2c_stop();
            return;
        }
    }
    i2c_stop();
    (void)oled_command(0xAFU);
}
