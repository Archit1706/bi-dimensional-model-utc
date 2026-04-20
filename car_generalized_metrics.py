"""
Car Mode Generalized Speed and Time Calculator
Using the Bidimensional Transportation Model (Khisty & Sriraj)

This script calculates generalized speed and generalized time metrics for car travel
based on OTP (OpenTripPlanner) data, with zone classification determining fixed costs.

Zone Classifications (based on destination TAZ):
- CBD: chicago=1 AND cbd=1 → fixed_cost = $37.28
- Suburb: chicago=0 AND cbd=0 → fixed_cost = $0
- City non-CBD: chicago=1 AND cbd=0 → fixed_cost = $20

Formulas:
- generalized_time = access_time + travel_time + (fixed_cost / VoT) + (variable_cost * distance / VoT)
- generalized_speed = distance / generalized_time
  OR equivalently:
- generalized_speed = (distance * VoT) / (VoT*(access_time + travel_time) + fixed_cost + variable_cost*distance)
"""

import pandas as pd
import numpy as np
from pathlib import Path


# =============================================================================
# PARAMETERS
# =============================================================================

# Car Mode Parameters
ACCESS_TIME_MINS = 10  # minutes
ACCESS_TIME_HOURS = ACCESS_TIME_MINS / 60  # convert to hours

VARIABLE_COST_PER_MILE = 0.92  # $/mile

# Fixed costs by zone classification
FIXED_COST_CBD = 37.28       # $ for CBD zones
FIXED_COST_SUBURB = 0.00     # $ for suburb zones  
FIXED_COST_CITY_NON_CBD = 20.00  # $ for city non-CBD zones

# Value of Time (VoT) levels - $/hour
# Based on income levels: low, mid, high
VOT_LOW = 14.64    # Low income
VOT_MID = 30.62    # Mid income
VOT_HIGH = 80.84   # High income

VOT_LEVELS = {
    'low': VOT_LOW,
    'mid': VOT_MID,
    'high': VOT_HIGH
}


# =============================================================================
# FUNCTIONS
# =============================================================================

def load_taz_classifications(taz_filepath):
    """
    Load TAZ zone classifications from Excel file.
    
    Returns a dictionary mapping zone17 (TAZ ID) to zone classification.
    """
    print(f"Loading TAZ classifications from: {taz_filepath}")
    
    df = pd.read_excel(taz_filepath, sheet_name='Traffic_Analysis_Zone_Geography')
    
    # Ensure required columns exist
    required_cols = ['zone17', 'cbd', 'chicago']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in TAZ file: {missing_cols}")
    
    # Create zone classification dictionary
    zone_classifications = {}
    zone_fixed_costs = {}
    
    for _, row in df.iterrows():
        zone_id = row['zone17']
        cbd = row['cbd']
        chicago = row['chicago']
        
        # Classify zone based on cbd and chicago values
        if chicago == 1 and cbd == 1:
            classification = 'CBD'
            fixed_cost = FIXED_COST_CBD
        elif chicago == 0 and cbd == 0:
            classification = 'Suburb'
            fixed_cost = FIXED_COST_SUBURB
        elif chicago == 1 and cbd == 0:
            classification = 'City_non_CBD'
            fixed_cost = FIXED_COST_CITY_NON_CBD
        else:
            # Handle edge case: chicago=0, cbd=1 (unlikely but possible)
            classification = 'Other'
            fixed_cost = FIXED_COST_SUBURB  # Default to suburb cost
        
        zone_classifications[zone_id] = classification
        zone_fixed_costs[zone_id] = fixed_cost
    
    print(f"  Loaded {len(zone_classifications)} TAZ zones")
    
    # Summary of classifications
    class_counts = pd.Series(zone_classifications.values()).value_counts()
    print(f"  Zone classification summary:")
    for cls, count in class_counts.items():
        print(f"    {cls}: {count} zones")
    
    return zone_classifications, zone_fixed_costs


def load_car_data(car_data_filepath):
    """
    Load car travel data from CSV file.
    
    Returns DataFrame with origin_taz, destination_taz, travel_distance_miles, travel_time_mins.
    """
    print(f"\nLoading car data from: {car_data_filepath}")
    
    df = pd.read_csv(car_data_filepath)
    
    # Ensure required columns exist
    required_cols = ['origin_taz', 'destination_taz', 'travel_distance_miles', 'travel_time_mins']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in car data file: {missing_cols}")
    
    print(f"  Loaded {len(df)} TAZ pairs")
    
    return df


def validate_and_flag_data(df):
    """
    Validate data and flag invalid/missing entries.
    
    Invalid entries include:
    - Missing origin or destination TAZ
    - Missing, zero, or negative travel distance
    - Missing, zero, or negative travel time
    - Unrealistic speeds (e.g., > 100 mph or < 1 mph for reachable routes)
    """
    print("\nValidating data...")
    
    df = df.copy()
    
    # Initialize validity flag
    df['is_valid'] = True
    df['invalid_reason'] = ''
    
    # Check for missing TAZ IDs
    mask_missing_origin = df['origin_taz'].isna()
    mask_missing_dest = df['destination_taz'].isna()
    df.loc[mask_missing_origin, 'is_valid'] = False
    df.loc[mask_missing_origin, 'invalid_reason'] += 'Missing origin TAZ; '
    df.loc[mask_missing_dest, 'is_valid'] = False
    df.loc[mask_missing_dest, 'invalid_reason'] += 'Missing destination TAZ; '
    
    # Check for missing/zero/negative distance
    mask_invalid_dist = df['travel_distance_miles'].isna() | (df['travel_distance_miles'] <= 0)
    df.loc[mask_invalid_dist, 'is_valid'] = False
    df.loc[mask_invalid_dist, 'invalid_reason'] += 'Invalid distance; '
    
    # Check for missing/zero/negative travel time
    mask_invalid_time = df['travel_time_mins'].isna() | (df['travel_time_mins'] <= 0)
    df.loc[mask_invalid_time, 'is_valid'] = False
    df.loc[mask_invalid_time, 'invalid_reason'] += 'Invalid travel time; '
    
    # Check for unrealistic speeds (only for valid distance/time pairs)
    mask_can_calc_speed = ~mask_invalid_dist & ~mask_invalid_time
    df.loc[mask_can_calc_speed, 'modal_speed_mph'] = (
        df.loc[mask_can_calc_speed, 'travel_distance_miles'] / 
        (df.loc[mask_can_calc_speed, 'travel_time_mins'] / 60)
    )
    
    # Flag unrealistic speeds (> 80 mph suggests highway/error, < 1 mph suggests data issue)
    mask_speed_too_high = df['modal_speed_mph'] > 80
    mask_speed_too_low = (df['modal_speed_mph'] < 1) & mask_can_calc_speed
    
    df.loc[mask_speed_too_high, 'invalid_reason'] += 'Speed > 80 mph (flagged); '
    df.loc[mask_speed_too_low, 'invalid_reason'] += 'Speed < 1 mph (flagged); '
    
    # Summary
    valid_count = df['is_valid'].sum()
    invalid_count = len(df) - valid_count
    print(f"  Valid pairs: {valid_count}")
    print(f"  Invalid pairs: {invalid_count}")
    
    if invalid_count > 0:
        print(f"  (Invalid pairs will have NaN for generalized metrics)")
    
    return df


def calculate_generalized_metrics(df, zone_classifications, zone_fixed_costs, vot_levels):
    """
    Calculate generalized speed and generalized time for each TAZ pair.
    
    Formulas (units: miles, hours, $):
    - generalized_time = access_time + travel_time + (fixed_cost / VoT) + (variable_cost * distance / VoT)
    - generalized_speed = distance / generalized_time
    """
    print("\nCalculating generalized metrics...")
    
    df = df.copy()
    
    # Convert travel time from minutes to hours
    df['travel_time_hours'] = df['travel_time_mins'] / 60
    
    # Get zone classification and fixed cost for each destination
    df['dest_classification'] = df['destination_taz'].map(zone_classifications)
    df['fixed_cost'] = df['destination_taz'].map(zone_fixed_costs)
    
    # Flag destinations with unknown classification
    mask_unknown_zone = df['dest_classification'].isna()
    if mask_unknown_zone.any():
        unknown_count = mask_unknown_zone.sum()
        print(f"  Warning: {unknown_count} destinations have unknown zone classification")
        df.loc[mask_unknown_zone, 'dest_classification'] = 'Unknown'
        df.loc[mask_unknown_zone, 'fixed_cost'] = 0  # Default to $0 for unknown zones
    
    # Calculate metrics for each VoT level
    for vot_name, vot_value in vot_levels.items():
        print(f"  Calculating for VoT ({vot_name}): ${vot_value}/hr")
        
        # Generalized time formula
        # Tg = access_time + travel_time + (fixed_cost / VoT) + (variable_cost * distance / VoT)
        gt_col = f'generalized_time_hours_{vot_name}'
        df[gt_col] = (
            ACCESS_TIME_HOURS +
            df['travel_time_hours'] +
            (df['fixed_cost'] / vot_value) +
            (VARIABLE_COST_PER_MILE * df['travel_distance_miles'] / vot_value)
        )
        
        # Generalized speed formula
        # Vg = distance / generalized_time
        gs_col = f'generalized_speed_mph_{vot_name}'
        df[gs_col] = df['travel_distance_miles'] / df[gt_col]
        
        # Set invalid rows to NaN
        df.loc[~df['is_valid'], gt_col] = np.nan
        df.loc[~df['is_valid'], gs_col] = np.nan
    
    return df


def generate_statistics(df, vot_levels):
    """
    Generate summary statistics for the calculated metrics.
    """
    print("\n" + "="*80)
    print("SUMMARY STATISTICS")
    print("="*80)
    
    valid_df = df[df['is_valid']].copy()
    
    # Overall statistics
    print(f"\nTotal TAZ pairs: {len(df)}")
    print(f"Valid pairs: {len(valid_df)}")
    print(f"Invalid pairs: {len(df) - len(valid_df)}")
    
    # Statistics by destination classification
    print(f"\n--- Statistics by Destination Zone Classification ---")
    for classification in ['CBD', 'Suburb', 'City_non_CBD', 'Unknown']:
        class_df = valid_df[valid_df['dest_classification'] == classification]
        if len(class_df) > 0:
            print(f"\n{classification} zones ({len(class_df)} pairs):")
            print(f"  Distance (miles): mean={class_df['travel_distance_miles'].mean():.2f}, "
                  f"min={class_df['travel_distance_miles'].min():.2f}, "
                  f"max={class_df['travel_distance_miles'].max():.2f}")
            print(f"  Travel time (mins): mean={class_df['travel_time_mins'].mean():.2f}, "
                  f"min={class_df['travel_time_mins'].min():.2f}, "
                  f"max={class_df['travel_time_mins'].max():.2f}")
            
            for vot_name in vot_levels.keys():
                gs_col = f'generalized_speed_mph_{vot_name}'
                gt_col = f'generalized_time_hours_{vot_name}'
                print(f"  VoT ({vot_name}): "
                      f"Gen. Speed={class_df[gs_col].mean():.2f} mph, "
                      f"Gen. Time={class_df[gt_col].mean()*60:.2f} mins")
    
    # Overall metrics by VoT
    print(f"\n--- Overall Generalized Metrics (valid pairs only) ---")
    for vot_name, vot_value in vot_levels.items():
        gs_col = f'generalized_speed_mph_{vot_name}'
        gt_col = f'generalized_time_hours_{vot_name}'
        print(f"\nVoT ({vot_name} = ${vot_value}/hr):")
        print(f"  Generalized Speed (mph):")
        print(f"    mean: {valid_df[gs_col].mean():.2f}")
        print(f"    std:  {valid_df[gs_col].std():.2f}")
        print(f"    min:  {valid_df[gs_col].min():.2f}")
        print(f"    max:  {valid_df[gs_col].max():.2f}")
        print(f"  Generalized Time (hours):")
        print(f"    mean: {valid_df[gt_col].mean():.3f} ({valid_df[gt_col].mean()*60:.2f} mins)")
        print(f"    std:  {valid_df[gt_col].std():.3f}")
        print(f"    min:  {valid_df[gt_col].min():.3f}")
        print(f"    max:  {valid_df[gt_col].max():.3f}")


def save_outputs(df, output_dir):
    """
    Save output files:
    1. Full results with all columns
    2. Clean results (valid pairs only, essential columns)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Full results
    full_output_path = output_dir / 'car_generalized_metrics_full.csv'
    df.to_csv(full_output_path, index=False)
    print(f"\nFull results saved to: {full_output_path}")
    
    # Clean results (valid pairs only)
    valid_df = df[df['is_valid']].copy()
    
    # Select essential columns
    essential_cols = [
        'origin_taz', 'destination_taz', 'dest_classification', 'fixed_cost',
        'travel_distance_miles', 'travel_time_mins', 'modal_speed_mph'
    ]
    
    # Add generalized metric columns
    for vot_name in VOT_LEVELS.keys():
        essential_cols.append(f'generalized_time_hours_{vot_name}')
        essential_cols.append(f'generalized_speed_mph_{vot_name}')
    
    clean_df = valid_df[essential_cols]
    clean_output_path = output_dir / 'car_generalized_metrics_clean.csv'
    clean_df.to_csv(clean_output_path, index=False)
    print(f"Clean results saved to: {clean_output_path}")
    
    # Invalid pairs (for review)
    invalid_df = df[~df['is_valid']].copy()
    if len(invalid_df) > 0:
        invalid_output_path = output_dir / 'car_invalid_pairs.csv'
        invalid_df.to_csv(invalid_output_path, index=False)
        print(f"Invalid pairs saved to: {invalid_output_path}")
    
    return full_output_path, clean_output_path


def main():
    """
    Main function to run the car generalized metrics calculation.
    """
    print("="*80)
    print("CAR MODE GENERALIZED METRICS CALCULATOR")
    print("Bidimensional Transportation Model (Khisty & Sriraj)")
    print("="*80)
    
    # File paths - UPDATE THESE TO YOUR FILE LOCATIONS
    taz_filepath = 'taz.xlsx'  # TAZ zone classification file
    car_data_filepath = 'car_data.csv'  # OTP car travel data
    output_dir = 'output'  # Output directory
    
    print(f"\n--- Parameters ---")
    print(f"Access time: {ACCESS_TIME_MINS} mins ({ACCESS_TIME_HOURS:.4f} hours)")
    print(f"Variable cost: ${VARIABLE_COST_PER_MILE}/mile")
    print(f"Fixed costs:")
    print(f"  CBD zones: ${FIXED_COST_CBD}")
    print(f"  Suburb zones: ${FIXED_COST_SUBURB}")
    print(f"  City non-CBD zones: ${FIXED_COST_CITY_NON_CBD}")
    print(f"Value of Time levels:")
    for name, value in VOT_LEVELS.items():
        print(f"  {name}: ${value}/hour")
    
    # Load TAZ classifications
    zone_classifications, zone_fixed_costs = load_taz_classifications(taz_filepath)
    
    # Load car data
    df = load_car_data(car_data_filepath)
    
    # Validate data
    df = validate_and_flag_data(df)
    
    # Calculate generalized metrics
    df = calculate_generalized_metrics(df, zone_classifications, zone_fixed_costs, VOT_LEVELS)
    
    # Generate statistics
    generate_statistics(df, VOT_LEVELS)
    
    # Save outputs
    save_outputs(df, output_dir)
    
    print("\n" + "="*80)
    print("Processing complete!")
    print("="*80)


if __name__ == '__main__':
    main()
