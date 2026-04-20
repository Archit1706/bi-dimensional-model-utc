"""
Calculate Generalized Speed and Generalized Time for Bicycle Mode
Using the Bidimensional Transportation Model (Khisty & Sriraj)

Bike Mode Parameters:
- access_time = 8 minutes = 0.1333 hours
- fixed_cost = $0
- variable_cost = $0.05/mile

Formulas:
generalized_speed = (distance * VoT) / (VoT*(access_time + travel_time) + fixed_cost + (variable_cost * distance))
generalized_time = access_time + travel_time + (fixed_cost / VoT) + (variable_cost * distance / VoT)

For bicycle (with fixed_cost = 0):
generalized_speed = (distance * VoT) / (VoT*(access_time + travel_time) + (variable_cost * distance))
generalized_time = access_time + travel_time + (variable_cost * distance / VoT)

Note: Unlike walking, bicycle generalized metrics ARE dependent on VoT due to the variable_cost term.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional
import sys


@dataclass
class BicycleMode:
    """Bicycle mode parameters for the bidimensional model"""
    name: str = "Bicycle"
    access_time: float = 8.0 / 60.0   # 8 minutes = 0.1333 hours
    fixed_cost: float = 0.0           # $
    variable_cost: float = 0.05       # $/mile
    
    
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


def process_bike_data(
    input_file: str,
    output_file: str,
    vot_values: Optional[List[Tuple[str, float]]] = None,
    bike_params: Optional[BicycleMode] = None
) -> pd.DataFrame:
    """
    Process bike data and calculate generalized metrics for each TAZ pair.
    
    Args:
        input_file: Path to input CSV with bike data
        output_file: Path to output CSV
        vot_values: List of (name, value) tuples for different VoT levels
        bike_params: BicycleMode dataclass with mode parameters
    
    Returns:
        DataFrame with calculated metrics
    """
    # Default VoT values based on income levels ($/hour)
    if vot_values is None:
        vot_values = [
            ("low", 14.64),    # Low income VoT
            ("mid", 30.62),    # Middle income VoT
            ("high", 80.84),   # High income VoT
        ]
    
    # Bicycle mode parameters
    if bike_params is None:
        bike_params = BicycleMode()
    
    # Read the bike data
    print(f"Reading bike data from: {input_file}")
    df = pd.read_csv(input_file)
    
    # Display initial data info
    print(f"\nInitial data shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
    
    # Print mode parameters
    print("\n--- Bicycle Mode Parameters ---")
    print(f"Access Time: {bike_params.access_time:.4f} hours ({bike_params.access_time * 60:.1f} minutes)")
    print(f"Fixed Cost: ${bike_params.fixed_cost:.2f}")
    print(f"Variable Cost: ${bike_params.variable_cost:.2f}/mile")
    
    # Handle missing/invalid data
    print("\n--- Data Quality Report ---")
    
    # Count initial issues
    initial_rows = len(df)
    
    # Check for missing values
    missing_distance = df['travel_distance_miles'].isna().sum()
    missing_time = df['travel_time_mins'].isna().sum()
    print(f"Missing distance values: {missing_distance}")
    print(f"Missing time values: {missing_time}")
    
    # Check for zero values (non-bikeable routes)
    zero_distance = (df['travel_distance_miles'] == 0).sum()
    zero_time = (df['travel_time_mins'] == 0).sum()
    print(f"Zero distance values: {zero_distance}")
    print(f"Zero time values: {zero_time}")
    
    # Create a flag for valid/bikeable routes
    df['is_bikeable'] = (
        df['travel_distance_miles'].notna() & 
        df['travel_time_mins'].notna() &
        (df['travel_distance_miles'] > 0) &
        (df['travel_time_mins'] > 0)
    )
    
    bikeable_count = df['is_bikeable'].sum()
    non_bikeable_count = len(df) - bikeable_count
    print(f"\nBikeable routes: {bikeable_count}")
    print(f"Non-bikeable routes (missing/zero/invalid): {non_bikeable_count}")
    
    # Convert travel time from minutes to hours
    df['travel_time_hours'] = df['travel_time_mins'] / 60.0
    
    # Calculate actual biking speed (miles/hour) for reference
    df['actual_speed_mph'] = np.where(
        df['is_bikeable'],
        df['travel_distance_miles'] / df['travel_time_hours'],
        np.nan
    )
    
    # Calculate total time including access time
    df['total_time_hours'] = np.where(
        df['is_bikeable'],
        bike_params.access_time + df['travel_time_hours'],
        np.nan
    )
    
    # Calculate transport cost
    df['transport_cost'] = np.where(
        df['is_bikeable'],
        bike_params.fixed_cost + (bike_params.variable_cost * df['travel_distance_miles']),
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
                access_time=bike_params.access_time,
                fixed_cost=bike_params.fixed_cost,
                variable_cost=bike_params.variable_cost
            ) if row['is_bikeable'] else np.nan,
            axis=1
        )
        
        # Generalized Time
        col_time = f'generalized_time_{vot_name}'
        df[col_time] = df.apply(
            lambda row: calculate_generalized_time(
                distance=row['travel_distance_miles'],
                travel_time=row['travel_time_hours'],
                vot=vot_value,
                access_time=bike_params.access_time,
                fixed_cost=bike_params.fixed_cost,
                variable_cost=bike_params.variable_cost
            ) if row['is_bikeable'] else np.nan,
            axis=1
        )
        
        # Generalized Cost (for reference)
        col_cost = f'generalized_cost_{vot_name}'
        df[col_cost] = np.where(
            df['is_bikeable'],
            df['transport_cost'] + (vot_value * df['total_time_hours']),
            np.nan
        )
    
    # Note about bicycle mode
    print("\n--- Important Note ---")
    print("For bicycle mode (access_time=0.1333hr, fixed_cost=$0, variable_cost=$0.05/mi):")
    print("  - Generalized Speed = (D * VoT) / (VoT*(0.1333 + travel_time) + 0.05*D)")
    print("  - Generalized Time = 0.1333 + travel_time + (0.05 * D / VoT)")
    print("Unlike walking, these metrics VARY with VoT due to the variable cost term.")
    
    # Summary statistics for bikeable routes
    print("\n--- Summary Statistics (Bikeable Routes Only) ---")
    bikeable_df = df[df['is_bikeable']]
    
    print(f"\nDistance (miles):")
    print(f"  Min: {bikeable_df['travel_distance_miles'].min():.3f}")
    print(f"  Max: {bikeable_df['travel_distance_miles'].max():.3f}")
    print(f"  Mean: {bikeable_df['travel_distance_miles'].mean():.3f}")
    print(f"  Median: {bikeable_df['travel_distance_miles'].median():.3f}")
    
    print(f"\nTravel Time (hours) - excluding access time:")
    print(f"  Min: {bikeable_df['travel_time_hours'].min():.3f}")
    print(f"  Max: {bikeable_df['travel_time_hours'].max():.3f}")
    print(f"  Mean: {bikeable_df['travel_time_hours'].mean():.3f}")
    print(f"  Median: {bikeable_df['travel_time_hours'].median():.3f}")
    
    print(f"\nTotal Time (hours) - including {bike_params.access_time*60:.0f} min access time:")
    print(f"  Min: {bikeable_df['total_time_hours'].min():.3f}")
    print(f"  Max: {bikeable_df['total_time_hours'].max():.3f}")
    print(f"  Mean: {bikeable_df['total_time_hours'].mean():.3f}")
    print(f"  Median: {bikeable_df['total_time_hours'].median():.3f}")
    
    print(f"\nActual Biking Speed (mph) - distance/travel_time only:")
    print(f"  Min: {bikeable_df['actual_speed_mph'].min():.3f}")
    print(f"  Max: {bikeable_df['actual_speed_mph'].max():.3f}")
    print(f"  Mean: {bikeable_df['actual_speed_mph'].mean():.3f}")
    print(f"  Median: {bikeable_df['actual_speed_mph'].median():.3f}")
    
    print(f"\nTransport Cost ($) - variable_cost * distance:")
    print(f"  Min: ${bikeable_df['transport_cost'].min():.4f}")
    print(f"  Max: ${bikeable_df['transport_cost'].max():.4f}")
    print(f"  Mean: ${bikeable_df['transport_cost'].mean():.4f}")
    print(f"  Median: ${bikeable_df['transport_cost'].median():.4f}")
    
    # Generalized speed comparison across VoT levels
    print(f"\nGeneralized Speed by VoT level (mph):")
    for vot_name, vot_value in vot_values:
        col = f'generalized_speed_{vot_name}'
        print(f"  VoT_{vot_name} (${vot_value}/hr): "
              f"Min={bikeable_df[col].min():.3f}, "
              f"Mean={bikeable_df[col].mean():.3f}, "
              f"Max={bikeable_df[col].max():.3f}")
    
    print(f"\nGeneralized Time by VoT level (hours):")
    for vot_name, vot_value in vot_values:
        col = f'generalized_time_{vot_name}'
        print(f"  VoT_{vot_name} (${vot_value}/hr): "
              f"Min={bikeable_df[col].min():.3f}, "
              f"Mean={bikeable_df[col].mean():.3f}, "
              f"Max={bikeable_df[col].max():.3f}")
    
    # Save results
    print(f"\nSaving results to: {output_file}")
    df.to_csv(output_file, index=False)
    
    # Also save a clean version with only essential columns
    essential_cols = [
        'origin_taz', 'destination_taz', 
        'travel_distance_miles', 'travel_time_mins', 'travel_time_hours',
        'is_bikeable', 'actual_speed_mph', 'total_time_hours', 'transport_cost'
    ]
    
    # Add generalized speed/time/cost columns for each VoT
    for vot_name, _ in vot_values:
        essential_cols.extend([
            f'generalized_speed_{vot_name}',
            f'generalized_time_{vot_name}',
            f'generalized_cost_{vot_name}'
        ])
    
    clean_output = output_file.replace('.csv', '_clean.csv')
    df[essential_cols].to_csv(clean_output, index=False)
    print(f"Clean version saved to: {clean_output}")
    
    return df


def create_sample_data(output_file: str):
    """Create a sample bike_data.csv for testing"""
    sample_data = {
        'origin_taz': [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0],
        'destination_taz': [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 1.0, 3.0, 1.0, 2.0],
        # Bike distances typically longer than walk, speeds ~10-15 mph
        'travel_distance_miles': [0.5, 1.2, 2.0, 3.5, 5.0, 8.0, 0.5, 1.0, 1.2, 1.0],
        'travel_time_mins': [3.0, 7.2, 12.0, 21.0, 30.0, 48.0, 3.0, 6.0, 7.2, 6.0]
    }
    
    # Add some problematic data for testing
    sample_data['origin_taz'].extend([4.0, 5.0, 6.0])
    sample_data['destination_taz'].extend([5.0, 6.0, 7.0])
    sample_data['travel_distance_miles'].extend([np.nan, 0.0, 4.0])  # missing, zero, valid
    sample_data['travel_time_mins'].extend([15.0, 20.0, 0.0])        # valid, valid, zero
    
    df = pd.DataFrame(sample_data)
    df.to_csv(output_file, index=False)
    print(f"Sample data created: {output_file}")
    return df


if __name__ == "__main__":
    # Configuration
    INPUT_FILE = "bike_data.csv"
    OUTPUT_FILE = "bike_generalized_metrics.csv"
    
    # Value of Time configurations ($/hour)
    # Based on income levels as specified
    VOT_VALUES = [
        ("low", 14.64),     # Low income VoT
        ("mid", 30.62),     # Middle income VoT
        ("high", 80.84),    # High income VoT
    ]
    
    # Bicycle mode parameters
    BIKE_PARAMS = BicycleMode(
        name="Bicycle",
        access_time=8.0 / 60.0,   # 8 minutes converted to hours
        fixed_cost=0.0,           # $0
        variable_cost=0.05        # $0.05/mile
    )
    
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
    
    # Process the bike data
    print("=" * 60)
    print("BICYCLE MODE GENERALIZED METRICS CALCULATOR")
    print("Using Bidimensional Transportation Model (Khisty & Sriraj)")
    print("=" * 60)
    
    result_df = process_bike_data(
        input_file=INPUT_FILE,
        output_file=OUTPUT_FILE,
        vot_values=VOT_VALUES,
        bike_params=BIKE_PARAMS
    )
    
    print("\n" + "=" * 60)
    print("Processing complete!")
    print("=" * 60)
