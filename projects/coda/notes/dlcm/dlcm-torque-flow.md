# DLCM Torque Flow — Mermaid re-transcription

Re-transcription of `dlcm-torque-flow-chart.png` for review. Source of truth is the PNG; this file exists so the topology can be checked in text form.

Switch-block convention (Simulink default): when the control input is non-zero / true, the **top** data input is passed; otherwise the **bottom** data input is passed.

```mermaid
flowchart LR
    %% ============ Column 1: Inputs ============
    subgraph C1 [Inputs]
        direction TB
        IN1[/"(1) TorqueDemand"/]
        IN5[/"(5) VehicleSpeed"/]
        IN3[/"(3) BrakePressure"/]
        IN2[/"(2) BrakePressure_Valid"/]
        IN4[/"(4) BrakeSwitch"/]
    end

    %% ============ Column 2: Calibrations ============
    subgraph C2 [Calibrations]
        direction TB
        LUT_VS["gradientLimiterPositive_VehSpd<br/>1-D T(u)"]
        LUT_TLP["gradientLimiterPositive_TrqLast<br/>1-D T(u)"]
        LUT_BP["gradientLimiterNegative_BrakePress<br/>1-D T(u)"]
        K_ON["gradientLimiterNegative_BrkSwOn<br/>(Constant1)"]
        K_OFF["gradientLimiterNegative_BrkSwOff<br/>(Constant)"]
        LUT_TLN["gradientLimiterNegative_TrqLast<br/>1-D T(u)"]
    end

    %% ============ Column 3: Switches and reductions ============
    subgraph C3 [Select / Reduce]
        direction TB
        MIN_P((min))
        REL{{"&gt;"}}
        SW_BSW{{"Switch<br/>ctrl: BrakeSwitch"}}
        SW_BPV{{"Switch<br/>ctrl: BPValid"}}
        MIN_N((min))
    end

    %% ============ Column 4: Gradient limit ============
    subgraph C4 [Gradient Limit]
        direction TB
        LIMP["limit_positive_gradient<br/>(enable)"]
        NOT[["NOT"]]
        LIMN["limit_negative_gradient<br/>(enable)"]
    end

    %% ============ Column 5: Merge / output / feedback ============
    subgraph C5 [Output]
        direction TB
        MERGE((Merge))
        OUT[/"limited_torque_demand"/]
        UD["Unit Delay<br/>1/z"]
    end

    %% ---- Positive path ----
    IN5 --> LUT_VS --> MIN_P
    LUT_TLP --> MIN_P
    MIN_P -->|gradient_limit| LIMP
    LIMP -->|limited_torque| MERGE

    %% ---- Negative path: BrakeSwitch -> constant selector ----
    K_ON  -->|top input| SW_BSW
    K_OFF -->|bottom input| SW_BSW
    IN4 -->|ctrl| SW_BSW

    %% ---- Negative path: BrakePressure_Valid selects LUT vs constant ----
    IN3 --> LUT_BP
    LUT_BP -->|top input| SW_BPV
    SW_BSW -->|bottom input| SW_BPV
    IN2 -->|ctrl| SW_BPV

    %% ---- Negative path: min with TrqLast LUT ----
    SW_BPV --> MIN_N
    LUT_TLN --> MIN_N
    MIN_N -->|gradient_limit| LIMN
    LIMN -->|limited_torque| MERGE

    %% ---- Path selection ----
    IN1 -->|top input| REL
    UD  -->|bottom input| REL
    REL -->|enable| LIMP
    REL --> NOT
    NOT -->|enable| LIMN

    %% ---- Output and feedback loop ----
    MERGE --> OUT
    MERGE --> UD
    UD -->|TrqLast| LUT_TLP
    UD -->|TrqLast| LUT_TLN
```

## Calibration items implied by the chart

Four 1-D lookup tables and two scalar constants:

| Name | Type | Indexed by |
|---|---|---|
| `gradientLimiterPositive_VehSpd` | 1-D LUT | VehicleSpeed |
| `gradientLimiterPositive_TrqLast` | 1-D LUT | TrqLast (z&#8315;&#185;) |
| `gradientLimiterNegative_BrakePress` | 1-D LUT | BrakePressure |
| `gradientLimiterNegative_TrqLast` | 1-D LUT | TrqLast (z&#8315;&#185;) |
| `gradientLimiterNegative_BrkSwOn` | scalar constant | — |
| `gradientLimiterNegative_BrkSwOff` | scalar constant | — |

## Effective rate-limit equations

Positive path (active when `TorqueDemand > limited_torque_demand_prev`):

```
rate_limit_pos = min( gradientLimiterPositive_VehSpd[VehicleSpeed],
                      gradientLimiterPositive_TrqLast[TrqLast] )
```

Negative path (active otherwise):

```
brk_sw_K        = BrakeSwitch ? gradientLimiterNegative_BrkSwOn
                              : gradientLimiterNegative_BrkSwOff
selector_out    = BrakePressure_Valid ? gradientLimiterNegative_BrakePress[BrakePressure]
                                      : brk_sw_K
rate_limit_neg  = min( selector_out,
                       gradientLimiterNegative_TrqLast[TrqLast] )
```
