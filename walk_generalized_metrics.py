"""
Calculate Generalized Speed and Generalized Time for Walking Mode
Using the Bidimensional Transportation Model (Khisty & Sriraj)

For walking mode:
- access_time = 0
- fixed_cost = 0  
- variable_cost = 0

Formulas:
generalized_speed = (distance * VoT) / (VoT*(access_time + travel_time) + fixed_cost + (variable_cost * distance))
generalized_time = access_time + travel_time + (fixed_cost / VoT) + (variable_cost * distance / VoT)

For walking (with all cost terms = 0), these simplify to:
generalized_speed = distance / travel_time  (independent of VoT)
generalized_time = travel_time (independent of VoT)

However, we keep VoT as a parameter for consistency and future extensibility
when comparing with other modes that have non-zero cost terms.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional
import sys


@dataclass
class WalkingMode:
    """Walking mode parameters for the bidimensional model"""
    name: str = "Walking"
    access_time: float = 0.0      # hours
    fixed_cost: float = 0.0       # $
    variable_cost: float = 0.0    # $/mile
    
    
def calculate_generalized_speed(
    distance: float,
    travel_time: float,
    vot: float,
    access_time: float = 0.0,
    fixed_cost: float = 0.0,
    variable_cost: float = 0.0
) -> float:
    """
    Calculate generalized speed using the bidimensional model formula.
    
    generalized_speed = (distance * VoT) / (VoT*(access_time + travel_time) + fixed_cost + (variable_cost * distance))
    
    Args:
        distance: Travel distance (miles)
        travel_time: Travel time (hours)
        vot: Value of Time ($/hour)
        access_time: Access time to mode (hours)
        fixed_cost: Fixed modal cost ($)
        variable_cost: Cost per unit distance ($/mile)
    
    Returns:
        Generalized speed (miles/hour)
    """
    numerator = distance * vot
    denominator = (vot * (access_time + travel_time)) + fixed_cost + (variable_cost * distance)
    
    if denominator == 0 or np.isnan(denominator):
        return np.nan
    
    return numerator / denominator


def calculate_generalized_time(
    distance: float,
    travel_time: float,
    vot: float,
    access_time: float = 0.0,
    fixed_cost: float = 0.0,
    variable_cost: float = 0.0
) -> float:
    """
    Calculate generalized time using the bidimensional model formula.
    
    generalized_time = access_time + travel_time + (fixed_cost / VoT) + (variable_cost * distance / VoT)
    
    Args:
        distance: Travel distance (miles)
        travel_time: Travel time (hours)
        vot: Value of Time ($/hour)
        access_time: Access time to mode (hours)
        fixed_cost: Fixed modal cost ($)
        variable_cost: Cost per unit distance ($/mile)
    
    Returns:
        Generalized time (hours)
    """
    if vot == 0 or np.isnan(vot):
        return np.nan
    
    return access_time + travel_time + (fixed_cost / vot) + (variable_cost * distance / vot)


def process_walk_data(
    input_file: str,
    output_file: str,
    vot_values: Optional[List[Tuple[str, float]]] = None
) -> pd.DataFrame:
    """
    Process walk data and calculate generalized metrics for each TAZ pair.
    
    Args:
        input_file: Path to input CSV with walk data
        output_file: Path to output CSV
        vot_values: List of (name, value) tuples for different VoT levels
                   Default: [("low", 7.25), ("mid", 16.75), ("high", 36.0)]
    
    Returns:
        DataFrame with calculated metrics
    """
    # Default VoT values based on income levels ($/hour)
    # These can be adjusted based on regional income data
    if vot_values is None:
        vot_values = [
            ("low", 7.25),    # Low income VoT
            ("mid", 16.75),   # Middle income VoT
            ("high", 36.0)    # High income VoT
        ]
    
    # Walking mode parameters (all zeros for walking)
    walk_mode = WalkingMode()
    
    # Read the walk data
    print(f"Reading walk data from: {input_file}")
    df = pd.read_csv(input_file)
    
    # Display initial data info
    print(f"\nInitial data shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
    
    # Handle missing/invalid data
    print("\n--- Data Quality Report ---")
    
    # Count initial issues
    initial_rows = len(df)
    
    # Check for missing values
    missing_distance = df['travel_distance_miles'].isna().sum()
    missing_time = df['travel_time_mins'].isna().sum()
    print(f"Missing distance values: {missing_distance}")
    print(f"Missing time values: {missing_time}")
    
    # Check for zero values (non-walkable routes)
    zero_distance = (df['travel_distance_miles'] == 0).sum()
    zero_time = (df['travel_time_mins'] == 0).sum()
    print(f"Zero distance values: {zero_distance}")
    print(f"Zero time values: {zero_time}")
    
    # Create a flag for valid/walkable routes
    df['is_walkable'] = (
        df['travel_distance_miles'].notna() & 
        df['travel_time_mins'].notna() &
        (df['travel_distance_miles'] > 0) &
        (df['travel_time_mins'] > 0)
    )
    
    walkable_count = df['is_walkable'].sum()
    non_walkable_count = len(df) - walkable_count
    print(f"\nWalkable routes: {walkable_count}")
    print(f"Non-walkable routes (missing/zero/invalid): {non_walkable_count}")
    
    # Convert travel time from minutes to hours
    df['travel_time_hours'] = df['travel_time_mins'] / 60.0
    
    # Calculate actual walking speed (miles/hour) for reference
    df['actual_speed_mph'] = np.where(
        df['is_walkable'],
        df['travel_distance_miles'] / df['travel_time_hours'],
        np.nan
    )
    
    # Calculate generalized metrics for each VoT level
    for vot_name, vot_value in vot_values:
        print(f"\nCalculating metrics for VoT_{vot_name} = ${vot_value}/hour")
        
        # Generalized Speed
        col_speed = f'generalized_speed_{vot_name}'
        df[col_speed] = df.apply(
            lambda row: calculate_generalized_speed(
                distance=row['travel_distance_miles'],
                travel_time=row['travel_time_hours'],
                vot=vot_value,
                access_time=walk_mode.access_time,
                fixed_cost=walk_mode.fixed_cost,
                variable_cost=walk_mode.variable_cost
            ) if row['is_walkable'] else np.nan,
            axis=1
        )
        
        # Generalized Time
        col_time = f'generalized_time_{vot_name}'
        df[col_time] = df.apply(
            lambda row: calculate_generalized_time(
                distance=row['travel_distance_miles'],
                travel_time=row['travel_time_hours'],
                vot=vot_value,
                access_time=walk_mode.access_time,
                fixed_cost=walk_mode.fixed_cost,
                variable_cost=walk_mode.variable_cost
            ) if row['is_walkable'] else np.nan,
            axis=1
        )
    
    # Note about walking mode
    print("\n--- Important Note ---")
    print("For walking mode (access_time=0, fixed_cost=0, variable_cost=0):")
    print("  - Generalized Speed = distance / travel_time (same for all VoT values)")
    print("  - Generalized Time = travel_time (same for all VoT values)")
    print("VoT columns are included for consistency when comparing with other modes.")
    
    # Summary statistics for walkable routes
    print("\n--- Summary Statistics (Walkable Routes Only) ---")
    walkable_df = df[df['is_walkable']]
    
    print(f"\nDistance (miles):")
    print(f"  Min: {walkable_df['travel_distance_miles'].min():.3f}")
    print(f"  Max: {walkable_df['travel_distance_miles'].max():.3f}")
    print(f"  Mean: {walkable_df['travel_distance_miles'].mean():.3f}")
    print(f"  Median: {walkable_df['travel_distance_miles'].median():.3f}")
    
    print(f"\nTravel Time (hours):")
    print(f"  Min: {walkable_df['travel_time_hours'].min():.3f}")
    print(f"  Max: {walkable_df['travel_time_hours'].max():.3f}")
    print(f"  Mean: {walkable_df['travel_time_hours'].mean():.3f}")
    print(f"  Median: {walkable_df['travel_time_hours'].median():.3f}")
    
    print(f"\nActual Walking Speed (mph):")
    print(f"  Min: {walkable_df['actual_speed_mph'].min():.3f}")
    print(f"  Max: {walkable_df['actual_speed_mph'].max():.3f}")
    print(f"  Mean: {walkable_df['actual_speed_mph'].mean():.3f}")
    print(f"  Median: {walkable_df['actual_speed_mph'].median():.3f}")
    
    # For walking, generalized speed equals actual speed (verify)
    speed_col = f'generalized_speed_{vot_values[0][0]}'
    print(f"\nGeneralized Speed (mph) - same as actual for walking:")
    print(f"  Min: {walkable_df[speed_col].min():.3f}")
    print(f"  Max: {walkable_df[speed_col].max():.3f}")
    print(f"  Mean: {walkable_df[speed_col].mean():.3f}")
    print(f"  Median: {walkable_df[speed_col].median():.3f}")
    
    # Save results
    print(f"\nSaving results to: {output_file}")
    df.to_csv(output_file, index=False)
    
    # Also save a clean version with only essential columns
    essential_cols = [
        'origin_taz', 'destination_taz', 
        'travel_distance_miles', 'travel_time_mins', 'travel_time_hours',
        'is_walkable', 'actual_speed_mph'
    ]
    
    # Add generalized speed/time columns for each VoT
    for vot_name, _ in vot_values:
        essential_cols.extend([
            f'generalized_speed_{vot_name}',
            f'generalized_time_{vot_name}'
        ])
    
    clean_output = output_file.replace('.csv', '_clean.csv')
    df[essential_cols].to_csv(clean_output, index=False)
    print(f"Clean version saved to: {clean_output}")
    
    return df


def create_sample_data(output_file: str):
    """Create a sample walk_data.csv for testing"""
    sample_data = {
        'origin_taz': [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0],
        'destination_taz': [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 1.0, 3.0, 1.0, 2.0],
        'travel_distance_miles': [0.2, 0.45, 0.7, 0.95, 1.2, 2.0, 0.2, 0.3, 0.45, 0.3],
        'travel_time_mins': [4.23, 9.6, 15.67, 21.45, 27.27, 45.48, 4.23, 6.5, 9.6, 6.5]
    }
    
    # Add some problematic data for testing
    sample_data['origin_taz'].extend([4.0, 5.0, 6.0])
    sample_data['destination_taz'].extend([5.0, 6.0, 7.0])
    sample_data['travel_distance_miles'].extend([np.nan, 0.0, 1.5])  # missing, zero, valid
    sample_data['travel_time_mins'].extend([10.0, 15.0, 0.0])        # valid, valid, zero
    
    df = pd.DataFrame(sample_data)
    df.to_csv(output_file, index=False)
    print(f"Sample data created: {output_file}")
    return df


if __name__ == "__main__":
    # Configuration
    INPUT_FILE = "walk_data.csv"
    OUTPUT_FILE = "walk_generalized_metrics.csv"
    
    # Value of Time configurations ($/hour)
    # Based on income levels - adjust these based on regional data
    VOT_VALUES = [
        ("low", 7.25),     # Low income (~$15k/year assuming 70% of hourly wage)
        ("mid", 16.75),    # Middle income (~$35k/year)
        ("high", 36.0),    # High income (~$75k/year)
    ]
    
    # Check command line arguments
    if len(sys.argv) > 1:
        INPUT_FILE = sys.argv[1]
    if len(sys.argv) > 2:
        OUTPUT_FILE = sys.argv[2]
    
    # Check if input file exists, if not create sample data
    import os
    if not os.path.exists(INPUT_FILE):
        print(f"Input file '{INPUT_FILE}' not found.")
        print("Creating sample data for demonstration...")
        create_sample_data(INPUT_FILE)
    
    # Process the walk data
    print("=" * 60)
    print("WALKING MODE GENERALIZED METRICS CALCULATOR")
    print("Using Bidimensional Transportation Model (Khisty & Sriraj)")
    print("=" * 60)
    
    result_df = process_walk_data(
        input_file=INPUT_FILE,
        output_file=OUTPUT_FILE,
        vot_values=VOT_VALUES
    )
    
    print("\n" + "=" * 60)
    print("Processing complete!")
    print("=" * 60)
