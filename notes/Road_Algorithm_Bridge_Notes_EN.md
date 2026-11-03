# Connecting Valhalla and the solver

## 1. Connecting the two parts

I'd start by passing Valhalla's distance and travel-time matrices to the solver, including the depot. The solver would use these, along with the user's priorities and vehicles, to work out each vehicle's stop order and estimated times. We would then send the stop orders back to Valhalla to get the road paths for the map.

JSON files seem enough for the first test. They would let us check the same inputs and outputs together. We can move to an API once Valhalla is running somewhere we can both access. I already have local scripts to export stops, request matrices from Valhalla and load them into the solver. They've worked with a mock service; the next test is with Eren's setup.

## 2. What we need from each other

I can share sample Stockholm stops, vehicle and priority inputs, and solver outputs. From Eren, I'd need access to Valhalla with a fixed version, the available vehicle profiles, such as van and cargo bike, and an example matrix response. It would also help to measure how long matrices take for roughly 200 and 450 stops and check what traffic data is available.

We need to agree on stop IDs, coordinate order, metres and seconds as units, and how to mark unreachable stops. Required stops would stay hard constraints. For optional stops, we can use priority classes through the existing staged controller.

## 3. Things to check

Some stops may snap to the wrong street or be unreachable for a vehicle. I'd like the response to include how far each stop was moved to reach the road, so we can inspect those cases. The number of matrix entries grows with the square of the stop count, so we'll probably need to cache matrices later.

We also need to check whether the travel times include traffic. Without historical speeds, we could start with a clearly labelled peak/off-peak assumption. If those speeds are available, matrices for a few departure times would give us something to test rush-hour planning with.

## 4. The first demo

I'd keep it to 20-30 Stockholm stops, one depot and two vehicles, with a mix of required stops and optional priority classes. It should use real road matrices and show the routes, estimated times and unserved stops on a map. Traffic can follow once that works.

I'd like us to work through the first connection together. At the meeting, we can settle the data format, how we'll access Valhalla and who takes which task.
