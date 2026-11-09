#include "pid_store.h"
#include "ti_msp_dl_config.h"

/* Two 1 KB sectors at the end of MAIN Flash; excluded from the linker region. */
#define PID_SLOT_A 0x0001F800UL
#define PID_SLOT_B 0x0001FC00UL
#define PID_MAGIC  0x50494431UL
#define PID_VERSION 1UL

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t sequence;
    int32_t kp;
    int32_t ki;
    int32_t kd;
    uint32_t crc;
    uint32_t reserved;
} PidRecord;

/* Loaded once at boot; serial queries use this RAM copy. */
static PidRecord cached_record;
static uint32_t cached_address;
static int cache_initialized;
static int cache_valid;

static uint32_t record_crc(const PidRecord *record)
{
    const uint8_t *bytes = (const uint8_t *)record;
    uint32_t crc = 0xFFFFFFFFUL;
    unsigned i, bit;
    for (i = 0; i < 24; ++i) {
        crc ^= bytes[i];
        for (bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1U) ? 0xEDB88320UL : 0UL);
    }
    return ~crc;
}

void pid_store_defaults(PidGains *gains)
{
    gains->kp = 4000;
    gains->ki = 1500;
    gains->kd = 0;
}

int pid_store_valid_gains(const PidGains *gains)
{
    return gains->kp >= 0 && gains->kp <= 100000 &&
           gains->ki >= 0 && gains->ki <= 100000 &&
           gains->kd >= 0 && gains->kd <= 100000;
}

static int read_slot(uint32_t address, PidRecord *out)
{
    const volatile uint32_t *source = (const volatile uint32_t *)address;
    uint32_t *target = (uint32_t *)out;
    PidGains gains;
    unsigned i;
    for (i = 0; i < sizeof(PidRecord) / sizeof(uint32_t); ++i)
        target[i] = source[i];
    gains.kp = out->kp;
    gains.ki = out->ki;
    gains.kd = out->kd;
    return out->magic == PID_MAGIC && out->version == PID_VERSION &&
           out->crc == record_crc(out) && pid_store_valid_gains(&gains);
}

static int current_record(PidRecord *record, uint32_t *address)
{
    PidRecord a, b;
    int valid_a = read_slot(PID_SLOT_A, &a);
    int valid_b = read_slot(PID_SLOT_B, &b);
    if (!valid_a && !valid_b) return 0;
    if (valid_b && (!valid_a || (int32_t)(b.sequence - a.sequence) > 0)) {
        *record = b;
        *address = PID_SLOT_B;
    } else {
        *record = a;
        *address = PID_SLOT_A;
    }
    return 1;
}

static void ensure_cache(void)
{
    if (!cache_initialized) {
        cache_valid = current_record(&cached_record, &cached_address);
        cache_initialized = 1;
    }
}

int pid_store_load(PidGains *gains)
{
    ensure_cache();
    if (!cache_valid) return 0;
    gains->kp = cached_record.kp;
    gains->ki = cached_record.ki;
    gains->kd = cached_record.kd;
    return 1;
}

int pid_store_save(const PidGains *gains)
{
    PidRecord record, check;
    uint32_t target, primask;
    DL_FLASHCTL_COMMAND_STATUS status;
    if (!pid_store_valid_gains(gains)) return 0;
    ensure_cache();
    if (cache_valid && cached_record.kp == gains->kp &&
        cached_record.ki == gains->ki && cached_record.kd == gains->kd) return 1;
    target = cache_valid && cached_address == PID_SLOT_A ? PID_SLOT_B : PID_SLOT_A;
    record.magic = PID_MAGIC;
    record.version = PID_VERSION;
    record.sequence = cache_valid ? cached_record.sequence + 1U : 1U;
    record.kp = gains->kp;
    record.ki = gains->ki;
    record.kd = gains->kd;
    record.crc = record_crc(&record);
    record.reserved = 0xFFFFFFFFUL;

    /* Same-bank operations run from DriverLib RAM code. Keep ISRs out of Flash. */
    primask = __get_PRIMASK();
    __disable_irq();
    DL_FlashCTL_unprotectSector(FLASHCTL, target, DL_FLASHCTL_REGION_SELECT_MAIN);
    status = DL_FlashCTL_eraseMemoryFromRAM(FLASHCTL, target, DL_FLASHCTL_COMMAND_SIZE_SECTOR);
    if (status == DL_FLASHCTL_COMMAND_STATUS_PASSED) {
        DL_FlashCTL_unprotectSector(FLASHCTL, target, DL_FLASHCTL_REGION_SELECT_MAIN);
        status = DL_FlashCTL_programMemoryBlockingFromRAM64WithECCGenerated(
            FLASHCTL, target, (uint32_t *)&record,
            sizeof(record) / sizeof(uint32_t), DL_FLASHCTL_REGION_SELECT_MAIN);
    }
    __set_PRIMASK(primask);
    if (status != DL_FLASHCTL_COMMAND_STATUS_PASSED) return 0;
    if (!read_slot(target, &check)) return 0;
    if (check.sequence != record.sequence || check.kp != record.kp ||
        check.ki != record.ki || check.kd != record.kd) return 0;
    cached_record = check;
    cached_address = target;
    cache_valid = 1;
    return 1;
}
