import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { View, Text, StyleSheet } from 'react-native';
import { darkTheme } from './src/theme';

import { ThemeProvider, useTheme } from './src/screens/SettingsScreen';
import DashboardScreen from './src/screens/DashboardScreen';
import OrdersScreen from './src/screens/OrdersScreen';
import SkillsScreen from './src/screens/SkillsScreen';
import SettingsScreen from './src/screens/SettingsScreen';

const Tab = createBottomTabNavigator();

function TabIcon({ label, focused, color }) {
  const icons = {
    Dashboard: focused ? '◉' : '○',
    Orders: focused ? '☰' : '≡',
    Skills: focused ? '◆' : '◇',
    Settings: focused ? '⚙' : '⚬',
  };
  return (
    <View style={styles.tabIcon}>
      <Text style={[styles.tabIconText, { color }]}>{icons[label] || '●'}</Text>
    </View>
  );
}

function AppNavigator() {
  const theme = useTheme();

  return (
    <NavigationContainer
      theme={{
        dark: true,
        colors: {
          primary: theme.accent,
          background: theme.background,
          card: theme.surface,
          text: theme.text,
          border: theme.border,
          notification: theme.error,
        },
      }}
    >
      <Tab.Navigator
        screenOptions={({ route }) => ({
          headerStyle: {
            backgroundColor: theme.surface,
            shadowColor: 'transparent',
            elevation: 0,
          },
          headerTintColor: theme.text,
          headerTitleStyle: { fontWeight: '700' },
          tabBarStyle: {
            backgroundColor: theme.surface,
            borderTopColor: theme.border,
            borderTopWidth: 1,
            paddingBottom: 6,
            paddingTop: 6,
            height: 60,
          },
          tabBarActiveTintColor: theme.accent,
          tabBarInactiveTintColor: theme.textSecondary,
          tabBarIcon: ({ focused, color }) => (
            <TabIcon label={route.name} focused={focused} color={color} />
          ),
          tabBarLabelStyle: { fontSize: 11, fontWeight: '600' },
        })}
      >
        <Tab.Screen name="Dashboard" component={DashboardScreen} />
        <Tab.Screen name="Orders" component={OrdersScreen} />
        <Tab.Screen name="Skills" component={SkillsScreen} />
        <Tab.Screen name="Settings" component={SettingsScreen} />
      </Tab.Navigator>
      <StatusBar style="light" />
    </NavigationContainer>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AppNavigator />
    </ThemeProvider>
  );
}

const styles = StyleSheet.create({
  tabIcon: { alignItems: 'center', justifyContent: 'center' },
  tabIconText: { fontSize: 22, lineHeight: 24 },
});
