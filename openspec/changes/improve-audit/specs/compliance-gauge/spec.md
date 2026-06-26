# compliance-gauge Specification

## Purpose

**Layer: Frontend.** Reusable SVG circular progress ring component showing compliance percentage with neon color thresholds. Used on both `/auditoria` (per-user cards) and `/` (dashboard card).

## Requirements

### Requirement: Gauge renders percentage ring

The component SHALL accept `reported` (number) and `expected` (number) props and render a circular progress ring where the filled arc represents `reported / expected` as a percentage.

#### Scenario: Partial compliance (85%)

- GIVEN `reported=17` and `expected=20`
- WHEN the component renders
- THEN the ring shows 85% fill
- AND the center text displays "85%"
- AND the label below displays "17 de 20 días"

#### Scenario: Full compliance (100%)

- GIVEN `reported=20` and `expected=20`
- WHEN the component renders
- THEN the ring shows 100% fill
- AND the center text displays "100%"

#### Scenario: Zero compliance (0%)

- GIVEN `reported=0` and `expected=20`
- WHEN the component renders
- THEN the ring shows 0% fill (empty ring)
- AND the center text displays "0%"
- AND the label below displays "0 de 20 días"

### Requirement: Neon color thresholds

The ring color SHALL use neon theme variables: `--neon-green` when compliance ≥ 80%, `--neon-cyan` when ≥ 50% and < 80%, `--neon-pink` when < 50%.

#### Scenario: Green threshold (≥80%)

- GIVEN compliance is 85%
- WHEN the component renders
- THEN the ring stroke uses `--neon-green`

#### Scenario: Cyan threshold (≥50%, <80%)

- GIVEN compliance is 65%
- WHEN the component renders
- THEN the ring stroke uses `--neon-cyan`

#### Scenario: Pink threshold (<50%)

- GIVEN compliance is 30%
- WHEN the component renders
- THEN the ring stroke uses `--neon-pink`

#### Scenario: Exact boundary — 80%

- GIVEN compliance is exactly 80%
- WHEN the component renders
- THEN the ring stroke uses `--neon-green`

#### Scenario: Exact boundary — 50%

- GIVEN compliance is exactly 50%
- WHEN the component renders
- THEN the ring stroke uses `--neon-cyan`

### Requirement: Expected zero guard

The system SHALL display "Sin datos" when `expected` is 0, avoiding division by zero.

#### Scenario: No expected days

- GIVEN `reported=0` and `expected=0`
- WHEN the component renders
- THEN the center text displays "Sin datos"
- AND the ring shows 0% fill

### Requirement: Spanish labels

All visible text SHALL be in español neutro (tú form).

#### Scenario: Label format

- GIVEN any valid `reported` and `expected` values
- WHEN the component renders
- THEN the label below the ring reads "{X} de {Y} días"
